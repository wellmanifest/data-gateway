"""REST transport: POST /v2/line with one data-plane.line/v1 line; the response body is one line."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from data_gateway.auth import AuthError
from data_gateway.kernel import HTTP_STATUS

MEDIA = 'text/plain; charset=utf-8; profile="data-plane.line/v1"'
MAX_BODY = 65538


def _parse_content_length(raw_value):
    if raw_value is None:
        return 0
    if not isinstance(raw_value, str):
        return None
    stripped = raw_value.strip()
    if not stripped or not stripped.isascii() or not stripped.isdigit():
        return None
    return int(stripped)


def make_server(kernel, authenticator, host="127.0.0.1", port=8080):
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ValueError("Port must be an integer between 0 and 65535")
    authenticator.require_safe_bind(host)

    class Handler(BaseHTTPRequestHandler):
        server_version = "data-gateway"

        def log_message(self, *args):
            pass  # the audit stream is the request log

        def _drain_bounded(self, length):
            if 0 < length <= MAX_BODY:
                try:
                    self.rfile.read(length)
                except OSError:
                    self.close_connection = True

        def reply(self, status, body, media=MEDIA):
            raw = body.encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def violation(self, status, message):
            self.reply(status, json.dumps({"error": message}) + "\n", "application/json")

        def do_POST(self):
            if self.headers.get("Transfer-Encoding") is not None:
                self.close_connection = True
                return self.violation(400, "Transfer-Encoding is not supported")
            length = _parse_content_length(self.headers.get("Content-Length"))
            if length is None:
                self.close_connection = True
                return self.violation(400, "Invalid Content-Length")
            if length > MAX_BODY:
                self.close_connection = True
                return self.violation(413, "One line is at most 65536 bytes")
            if self.path != "/v2/line":
                self._drain_bounded(length)
                return self.violation(404, "Use POST /v2/line")
            essence = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if essence != "text/plain":
                self._drain_bounded(length)
                return self.violation(415, "Content-Type must be text/plain")
            try:
                scopes = authenticator.scopes(self.headers.get("Authorization"))
            except AuthError as error:
                self._drain_bounded(length)
                return self.violation(401, str(error))
            raw_body = self.rfile.read(length)
            if len(raw_body) != length:
                self.close_connection = True
                return self.violation(400, "Incomplete request body")
            try:
                text = raw_body.decode("utf-8")
            except UnicodeDecodeError:
                return self.violation(400, "Body is not UTF-8")
            outcome = kernel.execute(text, scopes)
            if outcome.kind == "violation":
                return self.violation(400, outcome.message)
            self.reply(HTTP_STATUS.get(outcome.code, 500), outcome.line + "\n")

    return HTTPServer((host, port), Handler)
