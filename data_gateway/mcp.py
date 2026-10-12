"""MCP stdio transport: one tool, `line.execute`, over newline-delimited JSON-RPC 2.0."""
from __future__ import annotations
import json

PROTOCOL='2025-06-18'
TOOL={'name':'line.execute',
      'description':'Execute one data-plane.line/v1 request line (`operation: target {vars}`) and return the `result:` or `error:` line.',
      'inputSchema':{'type':'object','properties':{'line':{'type':'string','maxLength':65536}},'required':['line'],'additionalProperties':False}}

def handle(kernel,message):
    """Return the JSON-RPC response for one message, or None for a notification."""
    method,ident=message.get('method'),message.get('id')
    if ident is None: return None
    def ok(result): return {'jsonrpc':'2.0','id':ident,'result':result}
    def fail(code,text): return {'jsonrpc':'2.0','id':ident,'error':{'code':code,'message':text}}
    if method=='initialize':
        return ok({'protocolVersion':PROTOCOL,'capabilities':{'tools':{}},'serverInfo':{'name':'data-gateway','version':'0.1.0'}})
    if method=='ping': return ok({})
    if method=='tools/list': return ok({'tools':[TOOL]})
    if method=='tools/call':
        params=message.get('params') or {}
        if params.get('name')!=TOOL['name']: return fail(-32602,'Unknown tool')
        text=(params.get('arguments') or {}).get('line')
        if not isinstance(text,str): return fail(-32602,'arguments.line must be a string')
        outcome=kernel.execute(text)  # stdio is the local operator's own process
        body=outcome.line if outcome.kind!='violation' else 'contract violation: '+outcome.message
        return ok({'content':[{'type':'text','text':body}],'isError':outcome.kind!='result'})
    return fail(-32601,'Method not found')

def serve(kernel,reader,writer):
    for raw in reader:
        if not raw.strip(): continue
        try: message=json.loads(raw)
        except ValueError:
            response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        else:
            response=handle(kernel,message) if isinstance(message,dict) else {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}}
        if response is not None:
            writer.write(json.dumps(response,ensure_ascii=False)+'\n');writer.flush()
