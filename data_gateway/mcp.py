"""MCP stdio transport: one tool, `line.execute`, over newline-delimited JSON-RPC 2.0."""
from __future__ import annotations

import json
import math

PROTOCOL = "2025-06-18"
MAX_LINE_CHARS = 65536
MAX_STDIO_FRAME_CHARS = 262144
TOOL = {
    "name": "line.execute",
    "description": "Execute one data-plane.line/v1 request line (`operation: target {vars}`) and return the `result:` or `error:` line.",
    "inputSchema": {
        "type": "object",
        "properties": {"line": {"type": "string", "maxLength": MAX_LINE_CHARS}},
        "required": ["line"],
        "additionalProperties": False,
    },
}


def _reject_nonfinite(constant):
    raise ValueError(f"Non-finite JSON constant: {constant}")


def _valid_rpc_id(ident):
    if ident is None or isinstance(ident, str):
        return True
    if isinstance(ident, bool):
        return False
    return isinstance(ident, (int, float)) and math.isfinite(ident)


def handle(kernel, message):
    """Return the JSON-RPC response for one message, or None for a notification."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    has_id = "id" in message
    ident = message.get("id")
    reply_id = ident if _valid_rpc_id(ident) else None

    def ok(result):
        return {"jsonrpc": "2.0", "id": reply_id, "result": result}

    def fail(code, text):
        return {"jsonrpc": "2.0", "id": reply_id, "error": {"code": code, "message": text}}

    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str) or not message["method"]:
        return fail(-32600, "Invalid request")
    if not has_id:
        return None
    if not _valid_rpc_id(ident):
        return fail(-32600, "Invalid request id")

    method = message["method"]
    raw_params = message.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        return fail(-32602, "params must be an object")
    params = raw_params or {}

    if method == "initialize":
        return ok(
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "data-gateway", "version": "0.1.0"},
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [TOOL]})
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return fail(-32602, "Unknown tool")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return fail(-32602, "arguments must be an object")
        text = (arguments or {}).get("line")
        if not isinstance(text, str):
            return fail(-32602, "arguments.line must be a string")
        if len(text) > MAX_LINE_CHARS:
            return fail(-32602, "arguments.line exceeds maxLength")
        outcome = kernel.execute(text)  # stdio is the local operator's own process
        body = outcome.line if outcome.kind != "violation" else "contract violation: " + outcome.message
        return ok({"content": [{"type": "text", "text": body}], "isError": outcome.kind != "result"})
    return fail(-32601, "Method not found")


def serve(kernel, reader, writer):
    for raw in reader:
        if len(raw) > MAX_STDIO_FRAME_CHARS:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request too large"}}
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()
            continue
        if not raw.strip():
            continue
        try:
            message = json.loads(raw, parse_constant=_reject_nonfinite)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = (
                handle(kernel, message)
                if isinstance(message, dict)
                else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
            )
        if response is not None:
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()
