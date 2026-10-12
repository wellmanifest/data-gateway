import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import grpc
from data_gateway.auth import Authenticator
from data_gateway.grpc_server import SERVICE,decode_line,encode_line,make_server as make_grpc
from data_gateway.kernel import GatewayError,HTTP_STATUS,Kernel
from data_gateway.mcp import handle,serve
from data_gateway.rest import make_server as make_rest
from data_gateway.upstream import data_plane,verify

DP_ROOT,LINE,EVENTS=data_plane()
A,B,C='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','cccccccc-cccc-4ccc-8ccc-cccccccccccc'
PUBLISH='resource.publish: process://data-gateway/resource.publish/v2 {"contentBase64":"aGVsbG8K","idempotencyKey":"k1","mediaType":"text/plain","requestId":"'+A+'"}'
RESOURCE='urn:uuid:cf51e1b3-9032-5beb-9922-00627028b366'
# One scenario exercised identically by every transport: success, replay, conflict, read, not found, invalid input, unsupported.
SCENARIO=[
    PUBLISH,
    PUBLISH,
    PUBLISH.replace('aGVsbG8K','aGVsbG8gd29ybGQK'),
    'resource.read: '+RESOURCE+' {"requestId":"'+B+'"}',
    'resource.read: urn:uuid:99999999-9999-4999-8999-999999999999 {"requestId":"'+B+'"}',
    'resource.publish: process://data-gateway/resource.publish/v2 {"contentBase64":"aGVsbG8","idempotencyKey":"k2","mediaType":"text/plain","requestId":"'+C+'"}',
    'process.status: urn:uuid:11111111-1111-4111-8111-111111111111 {"requestId":"'+C+'"}',
]
EXPECTED_CODES=[None,None,'DP-CONCURRENCY-001',None,'GW-NOTFOUND-001','GW-INPUT-001','GW-UNSUPPORTED-001']

def fixed_clock(): return '2026-10-12T12:00:00Z'

def logs_module():
    path=verify('logs')
    spec=importlib.util.spec_from_file_location('pinned_logs_check',path/'standard/logs_check.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return path,module

class Fresh(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
    def kernel(self,name='gateway.sqlite'):
        kernel=Kernel(Path(self.folder.name)/name,clock=fixed_clock);self.addCleanup(kernel.close);return kernel

class KernelBehaviour(Fresh):
    def test_scenario_codes_and_replay(self):
        kernel=self.kernel();outcomes=[kernel.execute(line) for line in SCENARIO]
        self.assertEqual([o.code for o in outcomes],EXPECTED_CODES)
        first,replay=(LINE.line_to_response(outcomes[i].line) for i in (0,1))
        self.assertEqual((first['replayed'],replay['replayed']),(False,True))
        self.assertEqual(first['result'],replay['result'])
        read=LINE.line_to_response(outcomes[3].line)['result']
        self.assertEqual(read['contentBase64'],'aGVsbG8K');self.assertEqual(read['resource']['urn'],RESOURCE)

    def test_only_request_lines_execute(self):
        kernel=self.kernel()
        for text in ['result: urn:uuid:'+A+' {"replayed":false}','uri: sandbox://run {"cmd":"rm -rf /"}','broken']:
            with self.subTest(text):
                outcome=kernel.execute(text)
                self.assertEqual((outcome.kind,outcome.line),('violation',None))
        self.assertEqual(kernel.store.audit_jsonl(),b'')

    def test_missing_scope_is_refused_without_effects(self):
        kernel=self.kernel()
        outcome=kernel.execute(PUBLISH,scopes={'data:resource.read'})
        self.assertEqual(outcome.code,'GW-AUTH-001')
        self.assertEqual(kernel.store.domain_events(),[])
        self.assertEqual(kernel.execute(PUBLISH,scopes={'data:resource.publish'}).kind,'result')

    def test_domain_error_rolls_back_handler_effects_but_keeps_audit(self):
        kernel=self.kernel();original=kernel.handlers['resource.publish']
        def broken(*args):
            original(*args);raise GatewayError('DP-INTEGRITY-001','Injected failure after writes.')
        kernel.handlers['resource.publish']=broken
        self.assertEqual(kernel.execute(PUBLISH).code,'DP-INTEGRITY-001')
        self.assertEqual(kernel.store.domain_events(),[])
        self.assertIsNone(kernel.store.receipt('resource.publish','k1'))
        audit=[json.loads(line) for line in kernel.store.audit_jsonl().splitlines()]
        self.assertEqual([(e['outcome'],e['code']) for e in audit],[('FAILED','DP-INTEGRITY-001')])

    def test_domain_event_uses_the_data_plane_envelope(self):
        kernel=self.kernel();kernel.execute(PUBLISH)
        [raw]=kernel.store.domain_events();event=json.loads(raw)
        self.assertEqual(set(event),EVENTS.EVENT_FIELDS)
        self.assertEqual(EVENTS.canonical(event),raw)
        self.assertEqual(EVENTS.event_hash(event),event['eventHash'])
        self.assertEqual((event['eventType'],event['streamUrn'],event['inputHash']),('resource.published',RESOURCE,LINE.line_hash(PUBLISH)))
        self.assertEqual(LINE.line_to_event(LINE.event_to_line(event)),event)

    def test_history_is_immutable(self):
        kernel=self.kernel();kernel.execute(PUBLISH)
        for table in ('events','audit'):
            with self.subTest(table),self.assertRaises(Exception):
                kernel.store.db.execute(f'DELETE FROM {table}')

class AuditStream(Fresh):
    def test_audit_is_valid_wellmanifest_logs_and_has_line_projection(self):
        kernel=self.kernel()
        for line in SCENARIO: kernel.execute(line)
        logs_root,logs=logs_module()
        bundle,_=logs.load_contract(logs_root)
        catalog=dict(logs.load_error_catalog(logs_root,bundle))
        for root in (DP_ROOT,ROOT):
            declared=set(json.loads((root/'logs-error-catalog.v1.json').read_text())['diagnosticCodes'])
            catalog.update(logs.load_error_documents(root,bundle,directory_relative='errors',declared=declared))
        previous,prior=('0'*64),{}
        raw_lines=kernel.store.audit_jsonl().splitlines(keepends=True)
        self.assertEqual(len(raw_lines),len(SCENARIO))
        for number,raw in enumerate(raw_lines,1):
            event=json.loads(raw)
            self.assertEqual((logs.canonical(event)+'\n').encode(),raw)
            previous=logs.validate_event(event,bundle=bundle,catalog=catalog,root=ROOT,path=f'audit:{number}',
                stream='data-gateway-audit',sequence=number,previous_hash=previous,prior_events=prior)
            prior[event['eventId']]=event
            self.assertEqual(event['inputHash'],LINE.line_hash(SCENARIO[number-1]))
            self.assertEqual(event['code'],EXPECTED_CODES[number-1])
            self.assertEqual(LINE.line_to_event(LINE.event_to_line(event)),event)

    def test_gateway_error_catalog_passes_logs_error_adoption(self):
        logs_root,logs=logs_module()
        report=logs.validate_adopted_error_catalog(logs_root,ROOT/'logs-error-catalog.v1.json')
        self.assertTrue(report['valid'],report)

class Transports(Fresh):
    def scenario_cli(self):
        db=Path(self.folder.name)/'cli.sqlite';out=[]
        for text in SCENARIO:
            done=subprocess.run([sys.executable,'-m','data_gateway','--db',str(db),'exec',text],cwd=ROOT,capture_output=True,text=True)
            out.append((done.stdout.strip(),done.returncode))
        return out

    def scenario_rest(self,kernel,headers=None):
        server=make_rest(kernel,Authenticator(),'127.0.0.1',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        out=[]
        for text in SCENARIO:
            request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v2/line',data=text.encode(),method='POST',
                headers={'Content-Type':'text/plain; charset=utf-8',**(headers or {})})
            try:
                with urllib.request.urlopen(request) as response: out.append((response.read().decode().strip(),response.status))
            except urllib.error.HTTPError as error: out.append((error.read().decode().strip(),error.code))
        return out

    def scenario_grpc(self,kernel):
        server=make_grpc(kernel,Authenticator(),'127.0.0.1',0);server.start();self.addCleanup(server.stop,None)
        channel=grpc.insecure_channel(f'127.0.0.1:{server.bound_port}');self.addCleanup(channel.close)
        execute=channel.unary_unary(f'/{SERVICE}/Execute',request_serializer=encode_line,response_deserializer=decode_line)
        return [execute(text,timeout=10) for text in SCENARIO]

    def scenario_mcp(self,kernel):
        out=[]
        for number,text in enumerate(SCENARIO,1):
            response=handle(kernel,{'jsonrpc':'2.0','id':number,'method':'tools/call','params':{'name':'line.execute','arguments':{'line':text}}})
            out.append((response['result']['content'][0]['text'],response['result']['isError']))
        return out

    def test_all_transports_return_identical_lines(self):
        cli=self.scenario_cli()
        rest=self.scenario_rest(self.kernel('rest.sqlite'))
        grpc_lines=self.scenario_grpc(self.kernel('grpc.sqlite'))
        mcp=self.scenario_mcp(self.kernel('mcp.sqlite'))
        lines=[line for line,_ in cli]
        self.assertEqual([line for line,_ in rest],lines)
        self.assertEqual(grpc_lines,lines)
        self.assertEqual([line for line,_ in mcp],lines)
        self.assertEqual([code for _,code in cli],[0 if c is None else 1 for c in EXPECTED_CODES])
        self.assertEqual([status for _,status in rest],[HTTP_STATUS[c] for c in EXPECTED_CODES])
        self.assertEqual([error for _,error in mcp],[c is not None for c in EXPECTED_CODES])

    def test_contract_violations_per_transport(self):
        self.assertEqual(subprocess.run([sys.executable,'-m','data_gateway','--db',str(Path(self.folder.name)/'v.sqlite'),'exec','broken'],
                                        cwd=ROOT,capture_output=True).returncode,2)
        kernel=self.kernel()
        server=make_grpc(kernel,Authenticator(),'127.0.0.1',0);server.start();self.addCleanup(server.stop,None)
        with grpc.insecure_channel(f'127.0.0.1:{server.bound_port}') as channel:
            execute=channel.unary_unary(f'/{SERVICE}/Execute',request_serializer=encode_line,response_deserializer=decode_line)
            with self.assertRaises(grpc.RpcError) as caught: execute('broken',timeout=10)
            self.assertEqual(caught.exception.code(),grpc.StatusCode.INVALID_ARGUMENT)
        response=handle(kernel,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'line.execute','arguments':{'line':'broken'}}})
        self.assertTrue(response['result']['isError'])

    def test_mcp_stdio_session(self):
        kernel=self.kernel();out=io.StringIO()
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'unknown'}]
        serve(kernel,io.StringIO(''.join(json.dumps(m)+'\n' for m in messages)+'not json\n'),out)
        replies=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r.get('id') for r in replies],[1,2,3,None])
        self.assertEqual(replies[1]['result']['tools'][0]['name'],'line.execute')
        self.assertEqual((replies[2]['error']['code'],replies[3]['error']['code']),(-32601,-32700))

class Authentication(Fresh):
    def test_tokens_scopes_and_safe_bind(self):
        folder=Path(self.folder.name)
        (folder/'tokens.json').write_text(json.dumps({hashlib.sha256(b'reader-token').hexdigest():['data:resource.read']}))
        authenticator=Authenticator(folder/'tokens.json')
        kernel=self.kernel();server=make_rest(kernel,authenticator,'127.0.0.1',0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def post(token):
            request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v2/line',data=PUBLISH.encode(),method='POST',
                headers={'Content-Type':'text/plain','Authorization':f'Bearer {token}'} if token else {'Content-Type':'text/plain'})
            try:
                with urllib.request.urlopen(request) as response: return response.status,response.read().decode()
            except urllib.error.HTTPError as error: return error.code,error.read().decode()
        self.assertEqual(post(None)[0],401)
        self.assertEqual(post('wrong')[0],401)
        status,body=post('reader-token')
        self.assertEqual((status,LINE.line_to_error(body.strip(),codes={'GW-AUTH-001'})['code']),(403,'GW-AUTH-001'))
        self.assertNotIn('reader-token',kernel.store.audit_jsonl().decode())
        with self.assertRaisesRegex(ValueError,'loopback'):make_rest(kernel,Authenticator(),'0.0.0.0',0)

class ProtobufWire(unittest.TestCase):
    def test_line_codec_matches_protoc_output(self):
        try: from grpc_tools import protoc
        except ImportError: self.skipTest('grpcio-tools is not installed')
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(protoc.main(['protoc',f'-I{DP_ROOT/"proto"}',f'--python_out={out}',str(DP_ROOT/'proto/line.proto')]),0)
            sys.path.insert(0,out)
            try: import line_pb2
            finally: sys.path.remove(out)
        for text in ['',PUBLISH,'x'*300,'zażółć: urn:x:y']:
            with self.subTest(len(text)):
                self.assertEqual(encode_line(text),line_pb2.Line(text=text).SerializeToString())
                self.assertEqual(decode_line(line_pb2.Line(text=text).SerializeToString()),text)
        self.assertEqual(decode_line(b'\x10\x05'+encode_line('a')),'a')  # unknown varint field is skipped

if __name__=='__main__':
    unittest.main()
