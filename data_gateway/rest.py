"""REST transport: POST /v2/line with one data-plane.line/v1 line; the response body is one line."""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from data_gateway.auth import AuthError
from data_gateway.kernel import HTTP_STATUS

MEDIA='text/plain; charset=utf-8; profile="data-plane.line/v1"'
MAX_BODY=65538

def make_server(kernel,authenticator,host='127.0.0.1',port=8080):
    authenticator.require_safe_bind(host)

    class Handler(BaseHTTPRequestHandler):
        server_version='data-gateway'
        def log_message(self,*args): pass  # the audit stream is the request log

        def reply(self,status,body,media=MEDIA):
            raw=body.encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)

        def violation(self,status,message):
            self.reply(status,json.dumps({'error':message})+'\n','application/json')

        def do_POST(self):
            if self.path!='/v2/line': return self.violation(404,'Use POST /v2/line')
            if not self.headers.get('Content-Type','').startswith('text/plain'): return self.violation(415,'Content-Type must be text/plain')
            length=int(self.headers.get('Content-Length') or 0)
            if length>MAX_BODY: return self.violation(413,'One line is at most 65536 bytes')
            try: scopes=authenticator.scopes(self.headers.get('Authorization'))
            except AuthError as error: return self.violation(401,str(error))
            try: text=self.rfile.read(length).decode('utf-8')
            except UnicodeDecodeError: return self.violation(400,'Body is not UTF-8')
            outcome=kernel.execute(text,scopes)
            if outcome.kind=='violation': return self.violation(400,outcome.message)
            self.reply(HTTP_STATUS.get(outcome.code,500),outcome.line+'\n')

    return HTTPServer((host,port),Handler)
