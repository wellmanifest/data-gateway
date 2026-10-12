"""Shell transport and server launcher: `python -m data_gateway <command>`."""
from __future__ import annotations
import argparse
import json
import sys

from data_gateway.auth import Authenticator
from data_gateway.kernel import EXIT_CODE, Kernel

def main(argv=None):
    p=argparse.ArgumentParser(prog='data-gateway',description='data-plane.line/v1 reference gateway')
    p.add_argument('--db',default='data-gateway.sqlite',help='SQLite event store (one writer per file)')
    sub=p.add_subparsers(dest='command',required=True)
    run=sub.add_parser('exec',help='Execute a line argument or every stdin line; exit 0 result, 1 error line, 2 contract violation')
    run.add_argument('line',nargs='?')
    for name,port in (('rest',8080),('grpc',50051)):
        server=sub.add_parser(name,help=f'Serve {name.upper()}')
        server.add_argument('--host',default='127.0.0.1');server.add_argument('--port',type=int,default=port)
        server.add_argument('--tokens',help='JSON file mapping sha256(token) to scopes; required off loopback')
    sub.add_parser('mcp',help='Serve MCP over stdio')
    sub.add_parser('audit',help='Print the canonical wellmanifest/logs audit JSONL')
    args=p.parse_args(argv)
    kernel=Kernel(args.db)
    try:
        if args.command=='exec':
            items=[args.line] if args.line is not None else [line for line in sys.stdin.read().splitlines() if line.strip()]
            worst=0
            for item in items:
                outcome=kernel.execute(item)
                if outcome.kind=='violation': print(json.dumps({'error':outcome.message}),file=sys.stderr)
                else: print(outcome.line)
                worst=max(worst,EXIT_CODE[outcome.kind])
            return worst
        if args.command=='audit':
            sys.stdout.buffer.write(kernel.store.audit_jsonl());return 0
        if args.command=='mcp':
            from data_gateway.mcp import serve
            serve(kernel,sys.stdin,sys.stdout);return 0
        authenticator=Authenticator(args.tokens)
        if args.command=='rest':
            from data_gateway.rest import make_server
            server=make_server(kernel,authenticator,args.host,args.port)
            print(f'REST on http://{args.host}:{server.server_port}/v2/line',file=sys.stderr);server.serve_forever()
        else:
            from data_gateway.grpc_server import make_server
            server=make_server(kernel,authenticator,args.host,args.port)
            server.start();print(f'gRPC on {args.host}:{server.bound_port}',file=sys.stderr);server.wait_for_termination()
        return 0
    finally:
        kernel.close()

if __name__=='__main__':
    sys.exit(main())
