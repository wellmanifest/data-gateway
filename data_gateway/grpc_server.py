"""gRPC transport for data-plane proto/line.proto (wellmanifest.dataplane.line.v1.LineGateway).

`Line` has one string field, so its wire form is encoded here directly; tests check it against protoc output.
"""
from __future__ import annotations
from concurrent import futures

import grpc

from data_gateway.auth import AuthError

SERVICE='wellmanifest.dataplane.line.v1.LineGateway'
MAX_MESSAGE=65536+16

def _varint(value):
    out=bytearray()
    while True:
        byte=value&0x7f;value>>=7
        out.append(byte|0x80 if value else byte)
        if not value: return bytes(out)

def encode_line(text):
    raw=text.encode('utf-8')
    return b'\x0a'+_varint(len(raw))+raw if raw else b''

def decode_line(data):
    """Decode `Line`; unknown fields are skipped as proto3 requires, malformed input raises ValueError."""
    position,text=0,''
    while position<len(data):
        key,shift=0,0
        while True:
            byte=data[position];position+=1;key|=(byte&0x7f)<<shift;shift+=7
            if not byte&0x80: break
        field,wire=key>>3,key&7
        if wire==2:
            length,shift=0,0
            while True:
                byte=data[position];position+=1;length|=(byte&0x7f)<<shift;shift+=7
                if not byte&0x80: break
            value=data[position:position+length];position+=length
            if len(value)!=length: raise ValueError('Truncated field')
            if field==1: text=value.decode('utf-8')
        elif wire==0:
            while data[position]&0x80: position+=1
            position+=1
        elif wire==1: position+=8
        elif wire==5: position+=4
        else: raise ValueError('Unsupported wire type')
    return text

def _scopes(context,authenticator):
    metadata=dict(context.invocation_metadata())
    try: return authenticator.scopes(metadata.get('authorization'))
    except AuthError as error: context.abort(grpc.StatusCode.UNAUTHENTICATED,str(error))

def make_server(kernel,authenticator,host='127.0.0.1',port=50051):
    authenticator.require_safe_bind(host)

    def execute(text,context,scopes):
        outcome=kernel.execute(text,scopes)
        if outcome.kind=='violation': context.abort(grpc.StatusCode.INVALID_ARGUMENT,outcome.message)
        return outcome.line

    def unary(text,context):
        return execute(text,context,_scopes(context,authenticator))

    def stream(texts,context):
        scopes=_scopes(context,authenticator)
        for text in texts: yield execute(text,context,scopes)

    handler=grpc.method_handlers_generic_handler(SERVICE,{
        'Execute':grpc.unary_unary_rpc_method_handler(unary,request_deserializer=decode_line,response_serializer=encode_line),
        'Stream':grpc.stream_stream_rpc_method_handler(stream,request_deserializer=decode_line,response_serializer=encode_line)})
    server=grpc.server(futures.ThreadPoolExecutor(max_workers=2),handlers=[handler],
                       options=[('grpc.max_receive_message_length',MAX_MESSAGE),('grpc.max_send_message_length',MAX_MESSAGE)])
    server.bound_port=server.add_insecure_port(f'{host}:{port}')
    return server
