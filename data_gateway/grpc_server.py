"""gRPC transport for data-plane proto/line.proto (wellmanifest.dataplane.line.v1.LineGateway).

`Line` has one string field, so its wire form is encoded here directly; tests check it against protoc output.
"""

from __future__ import annotations

from concurrent import futures

import grpc

from data_gateway.auth import AuthError

SERVICE = "wellmanifest.dataplane.line.v1.LineGateway"
MAX_MESSAGE = 65536 + 16


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def _read_varint(data, position):
    value = 0
    shift = 0
    end = len(data)
    while True:
        if position >= end:
            raise ValueError("Truncated varint")
        byte = data[position]
        position += 1
        if shift == 63 and byte > 1:
            raise ValueError("Varint overflow")
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, position
        shift += 7
        if shift > 63:
            raise ValueError("Varint overflow")


def encode_line(text):
    raw = text.encode("utf-8")
    return b"\x0a" + _varint(len(raw)) + raw if raw else b""


def decode_line(data):
    """Decode `Line`; unknown fields are skipped as proto3 requires, malformed input raises ValueError."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("Wire payload must be bytes-like")
    if len(data) > MAX_MESSAGE:
        raise ValueError("Wire payload exceeds MAX_MESSAGE")
    position, text = 0, ""
    end = len(data)
    while position < end:
        key, position = _read_varint(data, position)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("Invalid protobuf field number 0")
        if wire == 2:
            length, position = _read_varint(data, position)
            if length > end - position:
                raise ValueError("Truncated field")
            value = bytes(data[position : position + length])
            position += length
            if field == 1:
                text = value.decode("utf-8")
        elif wire == 0:
            _, position = _read_varint(data, position)
        elif wire == 1:
            position += 8
            if position > end:
                raise ValueError("Truncated fixed64 field")
        elif wire == 5:
            position += 4
            if position > end:
                raise ValueError("Truncated fixed32 field")
        else:
            raise ValueError("Unsupported wire type")
    return text


def _scopes(context, authenticator):
    auth_values = [
        val for key, val in context.invocation_metadata() if key == "authorization"
    ]
    if len(auth_values) > 1:
        context.abort(
            grpc.StatusCode.UNAUTHENTICATED,
            "Multiple authorization headers are not allowed",
        )
    try:
        return authenticator.scopes(auth_values[0] if auth_values else None)
    except AuthError as error:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, str(error))


def make_server(kernel, authenticator, host="127.0.0.1", port=50051):
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ValueError("Port must be an integer between 0 and 65535")
    authenticator.require_safe_bind(host)

    def execute(text, context, scopes):
        outcome = kernel.execute(text, scopes)
        if outcome.kind == "violation":
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, outcome.message)
        return outcome.line

    def unary(text, context):
        return execute(text, context, _scopes(context, authenticator))

    def stream(texts, context):
        scopes = _scopes(context, authenticator)
        for text in texts:
            yield execute(text, context, scopes)

    handler = grpc.method_handlers_generic_handler(
        SERVICE,
        {
            "Execute": grpc.unary_unary_rpc_method_handler(
                unary, request_deserializer=decode_line, response_serializer=encode_line
            ),
            "Stream": grpc.stream_stream_rpc_method_handler(
                stream,
                request_deserializer=decode_line,
                response_serializer=encode_line,
            ),
        },
    )
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=2),
        handlers=[handler],
        options=[
            ("grpc.max_receive_message_length", MAX_MESSAGE),
            ("grpc.max_send_message_length", MAX_MESSAGE),
        ],
    )
    bind_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    server.bound_port = server.add_insecure_port(f"{bind_host}:{port}")
    return server
