"""One operation kernel behind every transport: line in, `result:`/`error:` line out, audit event per execution."""
from __future__ import annotations
import base64
import binascii
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import fastjsonschema

from data_gateway.store import Store, ZERO
from data_gateway.upstream import ROOT, data_plane

AUDIT_STREAM='data-gateway-audit'
PRODUCER='service:data-gateway'
AUTHORITY='authority:data-gateway'
RESOURCE_NAMESPACE=uuid.UUID('6f2c9a52-6d8e-5f1e-9c43-6b1f0d6a4e21')
MAX_CONTENT_BYTES=32768
SUBJECT=re.compile(r'[a-z][a-z0-9+.-]*:[A-Za-z0-9._:/-]+')
UUID_TEXT=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# Outcome of an error code in the audit stream; everything else is a rejected request.
FAILED_CODES={'DP-INTEGRITY-001','DP-SOURCE-001'}
# The only JSON Schema format in the operation catalog; same rule as jsonschema's uuid checker (hyphenated, any case).
FORMATS={'uuid':r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'}

# Draft 2020-12 treats these as annotations; fastjsonschema (draft-07) would assert contentEncoding.
ANNOTATIONS={'contentEncoding','contentMediaType'}

def _annotations_removed(schema):
    if isinstance(schema,dict): return {k:_annotations_removed(v) for k,v in schema.items() if k not in ANNOTATIONS}
    if isinstance(schema,list): return [_annotations_removed(v) for v in schema]
    return schema

class CompiledSchema:
    """Generated validator for one catalog schema; equivalence with Draft 2020-12 is pinned by tests/test_schema_equivalence.py."""
    def __init__(self,schema): self.check=fastjsonschema.compile(_annotations_removed(schema),formats=FORMATS)
    def valid(self,value):
        try: self.check(value)
        except fastjsonschema.JsonSchemaException: return False
        return True

class GatewayError(Exception):
    def __init__(self,code,message,retryable=False):
        super().__init__(message);self.code=code;self.message=message;self.retryable=retryable

@dataclass(frozen=True)
class Outcome:
    kind: str            # result | error | violation
    line: str|None       # canonical response line; None only for a contract violation
    code: str|None=None
    message: str|None=None

def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def error_codes():
    dp_root,_,_=data_plane()
    codes=set()
    for catalog in (dp_root/'logs-error-catalog.v1.json',ROOT/'logs-error-catalog.v1.json'):
        codes|=set(json.loads(catalog.read_text())['diagnosticCodes'])
    return codes

class Kernel:
    def __init__(self,database,*,tenant='00000000-0000-4000-8000-000000000000',clock=utc_now):
        _,self.line,self.events=data_plane()
        self.contracts=self.line.load_contracts(data_plane()[0])
        self.operations=self.contracts[1]
        self.codes=error_codes()
        self.store=Store(database);self.tenant=tenant;self.clock=clock
        self.handlers={'resource.publish':self._publish,'resource.read':self._read}
        self.validators={name:(CompiledSchema(op['inputSchema']),CompiledSchema(op['outputSchema']))
                         for name,op in self.operations.items()}
        self.event_schemas=frozenset(self.contracts[0]['events'])

    def close(self): self.store.close()

    def execute(self,text,scopes=None):
        """Execute one line. `scopes=None` means a local, already-authenticated operator (CLI, stdio MCP)."""
        line=self.line
        try:
            # One strict parse feeds classification and the input hash; classify() order is kept: event, uri, response, request.
            kind,target,variables=line.parse(text)
            if variables.get('schema') in self.event_schemas or kind not in self.operations:
                return Outcome('violation',None,message='Only operation request lines are executable')
            name,envelope=line.line_to_request(text,self.contracts)
            input_hash=hashlib.sha256(line.format_line(kind,target,variables).encode('utf-8')).hexdigest()
        except line.LineError as error:
            return Outcome('violation',None,message=str(error))
        request_id=envelope.get('requestId')
        if not isinstance(request_id,str) or not UUID_TEXT.fullmatch(request_id):
            return Outcome('violation',None,message='requestId must be a lowercase UUID')
        operation=self.operations[name]
        # Queries commit only their audit record: WAL synchronous=NORMAL survives a process crash, while every
        # command keeps synchronous=FULL (data-plane SQLite profile) for its events, projection and audit.
        with self.store.transaction(durable=operation['cqrs']!='query'):
            try:
                if not self.validators[name][0].valid(envelope):
                    raise GatewayError('GW-INPUT-001','Input does not match the operation schema.')
                if scopes is not None and not set(operation['scopes'])<=set(scopes):
                    raise GatewayError('GW-AUTH-001','Missing scope for this operation.')
                handler=self.handlers.get(name)
                if handler is None: raise GatewayError('GW-UNSUPPORTED-001','This gateway has no handler for the operation.')
                # Handler effects roll back on any domain error; the audit of the rejection still commits.
                self.store.db.execute('SAVEPOINT handler')
                try:
                    result,replayed=handler(envelope,input_hash,operation)
                    output={'requestId':request_id,'result':result,'replayed':replayed}
                    if not self.validators[name][1].valid(output):
                        raise GatewayError('DP-INTEGRITY-001','Handler output violates the operation contract.')
                except GatewayError:
                    self.store.db.execute('ROLLBACK TO handler');self.store.db.execute('RELEASE handler');raise
                self.store.db.execute('RELEASE handler')
                response=line.response_to_line(output);code=None
            except GatewayError as error:
                if error.code not in self.codes: raise
                response=line.error_to_line(request_id,error.code,retryable=error.retryable,message=error.message,codes=self.codes)
                code=error.code
            subject=target if SUBJECT.fullmatch(target) and len(target)<=160 else operation['uri']
            self.store.append_audit(lambda sequence,previous:self._audit(sequence,previous,request_id,subject,input_hash,code))
        return Outcome('error' if code else 'result',response,code=code)

    def _audit(self,sequence,previous,request_id,subject,input_hash,code):
        outcome='SUCCEEDED' if code is None else 'FAILED' if code in FAILED_CODES else 'REJECTED'
        return {'schema':'wellmanifest.logs/event/v1','eventId':f'event:data-gateway-{sequence}','stream':AUDIT_STREAM,
                'sequence':sequence,'eventType':'gateway.request_completed','correlationId':request_id,'causationId':None,
                'producer':PRODUCER,'source':'gateway.line','mode':'APPLY','outcome':outcome,'subjectState':None,
                'subjectRef':subject,'inputHash':input_hash,'evidence':[],'receiptRef':None,'code':code,
                'severity':{'SUCCEEDED':'INFO','REJECTED':'WARNING','FAILED':'ERROR'}[outcome],'occurredAt':self.clock(),
                'previousHash':previous,'rawOutputIncluded':False,'secretMaterialIncluded':False}

    def _publish(self,envelope,input_hash,operation):
        arguments=envelope['arguments']
        try: content=base64.b64decode(arguments['contentBase64'],validate=True)
        except (binascii.Error,ValueError): raise GatewayError('GW-INPUT-001','contentBase64 is not valid base64.') from None
        if base64.b64encode(content).decode()!=arguments['contentBase64']: raise GatewayError('GW-INPUT-001','contentBase64 is not canonical.')
        if len(content)>MAX_CONTENT_BYTES: raise GatewayError('DP-MEMORY-001','Content exceeds the inline byte budget.')
        key=envelope.get('idempotencyKey') or envelope['requestId']
        request_hash=self.events.digest({'operation':operation['name'],'arguments':arguments})
        existing=self.store.receipt(operation['name'],key)
        if existing:
            if existing[0]!=request_hash: raise GatewayError('DP-CONCURRENCY-001','Idempotency key was used with different input.')
            return json.loads(existing[1]),True
        urn='urn:uuid:'+str(uuid.uuid5(RESOURCE_NAMESPACE,f'{self.tenant}:{key}'))
        sha256=hashlib.sha256(content).hexdigest()
        version,previous=self.store.stream_head(urn)
        if version: raise GatewayError('DP-CONCURRENCY-001','Resource stream already exists.')
        data={'byteLength':str(len(content)),'mediaType':arguments['mediaType'],'sha256':sha256}
        event={'schema':'data-plane.domain-event/v1','eventUrn':'urn:uuid:'+str(uuid.uuid5(RESOURCE_NAMESPACE,f'{urn}:1')),
               'tenantId':self.tenant,'streamUrn':urn,'streamVersion':'1','eventType':'resource.published','schemaVersion':1,
               'processUri':operation['uri'],'commandId':envelope['requestId'],'correlationId':envelope['requestId'],
               'causationUrn':None,'occurredAt':self.clock(),'authorityId':AUTHORITY,'authorityEpoch':'1',
               'planHash':self.events.digest({'operationUri':operation['uri'],'inputHash':input_hash,'scopes':operation['scopes']}),
               'inputHash':input_hash,'previousHash':ZERO,'data':data}
        event['eventHash']=self.events.event_hash(event)
        self.store.append_event(event)
        self.store.put_resource(urn,sha256,content,arguments['mediaType'],1)
        result={'urn':urn,'sha256':sha256,'mediaType':arguments['mediaType'],'byteLength':str(len(content))}
        self.store.put_receipt(operation['name'],key,request_hash,result)
        return result,False

    def _read(self,envelope,input_hash,operation):
        urn=envelope['arguments']['urn'];row=self.store.resource(urn)
        if row is None: raise GatewayError('GW-NOTFOUND-001','No resource has this URN.')
        sha256,media_type,byte_length,content=row
        if hashlib.sha256(content).hexdigest()!=sha256: raise GatewayError('DP-INTEGRITY-001','Stored content does not match its digest.')
        return {'resource':{'urn':urn,'sha256':sha256,'mediaType':media_type,'byteLength':str(byte_length)},
                'contentBase64':base64.b64encode(content).decode()},False

# Transport mapping of a response; transports differ only in how they carry the same line.
HTTP_STATUS={None:200,'GW-INPUT-001':400,'GW-AUTH-001':403,'GW-NOTFOUND-001':404,'DP-CONCURRENCY-001':409,
             'DP-MEMORY-001':413,'GW-UNSUPPORTED-001':501,'DP-INTEGRITY-001':500,'DP-SOURCE-001':503}
EXIT_CODE={'result':0,'error':1,'violation':2}
