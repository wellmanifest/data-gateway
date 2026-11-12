"""Adversarial transport, auth, protobuf wire, and store telemetry hardening tests."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

import grpc

from data_gateway.auth import Authenticator, AuthError
from data_gateway.cli import MAX_STDIN_LINE_CHARS, _exec_stdin
from data_gateway.grpc_server import SERVICE, decode_line, encode_line
from data_gateway.grpc_server import make_server as make_grpc
from data_gateway.kernel import Kernel
from data_gateway.mcp import MAX_LINE_CHARS, MAX_STDIO_FRAME_CHARS, handle, serve
from data_gateway.rest import make_server as make_rest
from data_gateway.store import MAX_BATCH_HISTORY, Store


def _fixed_clock():
    return "2026-11-11T08:00:00Z"


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def kernel(self, name="hardening.sqlite"):
        k = Kernel(self.root / name, clock=_fixed_clock)
        self.addCleanup(k.close)
        return k

    def test_auth_rejects_symlinks_duplicate_digests_invalid_hex_and_non_loopback_hosts(
        self,
    ):
        real_file = self.root / "real-auth.json"
        digest = hashlib.sha256(b"alpha-cred").hexdigest()
        real_file.write_text(
            json.dumps({digest: ["data:resource.read"]}), encoding="utf-8"
        )

        link_file = self.root / "link-auth.json"
        os.symlink(real_file, link_file)
        with self.assertRaises(ValueError):
            Authenticator(link_file)

        dup_file = self.root / "dup-auth.json"
        dup_file.write_text(
            f'{{"{digest}": ["a"], "{digest}": ["b"]}}', encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            Authenticator(dup_file)

        case_dup = self.root / "case-dup-auth.json"
        case_dup.write_text(
            json.dumps({digest.lower(): ["a"], digest.upper(): ["b"]}), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            Authenticator(case_dup)

        bad_key = self.root / "bad-key.json"
        bad_key.write_text(
            json.dumps({"not-a-sha256": ["data:resource.read"]}), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            Authenticator(bad_key)

        bad_scope = self.root / "bad-scope.json"
        bad_scope.write_text(json.dumps({digest: [{"nested": 1}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            Authenticator(bad_scope)

        open_auth = Authenticator()
        for unsafe_host in ("0.0.0.0", "localhost", "::ffff:127.0.0.1", "::1%lo", ""):
            with self.subTest(unsafe_host), self.assertRaises(ValueError):
                open_auth.require_safe_bind(unsafe_host)
        open_auth.require_safe_bind("127.0.0.1")
        open_auth.require_safe_bind("::1")

        strict_auth = Authenticator(real_file)
        with self.assertRaises(AuthError):
            strict_auth.scopes("Bearer ")
        with self.assertRaises(AuthError):
            strict_auth.scopes("Bearer " + ("x" * 5000))
        self.assertEqual(
            strict_auth.scopes("Bearer alpha-cred"), frozenset({"data:resource.read"})
        )

    def test_rest_rejects_negative_and_non_integer_content_length_and_transfer_encoding(
        self,
    ):
        k = self.kernel()
        server = make_rest(k, Authenticator(), "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def raw_post(path, headers, body=b""):
            conn = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            try:
                conn.putrequest("POST", path)
                for h_key, h_val in headers.items():
                    conn.putheader(h_key, h_val)
                conn.endheaders()
                if body:
                    conn.send(body)
                resp = conn.getresponse()
                return resp.status, json.loads(resp.read().decode("utf-8"))
            finally:
                conn.close()

        status, payload = raw_post(
            "/v2/line", {"Content-Type": "text/plain", "Content-Length": "-1"}
        )
        self.assertEqual(status, 400)
        self.assertIn("Content-Length", payload["error"])

        status, payload = raw_post(
            "/v2/line", {"Content-Type": "text/plain", "Content-Length": "abc"}
        )
        self.assertEqual(status, 400)

        status, payload = raw_post(
            "/v2/line", {"Content-Type": "text/plain", "Transfer-Encoding": "chunked"}
        )
        self.assertEqual(status, 400)

        status, payload = raw_post(
            "/v2/line",
            {"Content-Type": "text/plain-evil", "Content-Length": "2"},
            b"{}",
        )
        self.assertEqual(status, 415)

        # Case-insensitive Content-Type essence is accepted cleanly
        read_line = 'resource.read: urn:uuid:99999999-9999-4999-8999-999999999999 {"requestId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}'
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            conn.request(
                "POST",
                "/v2/line",
                body=read_line.encode("utf-8"),
                headers={"Content-Type": "Text/Plain; charset=utf-8"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            self.assertTrue(resp.read().decode("utf-8").startswith("error:"))
        finally:
            conn.close()

    def test_mcp_handles_non_object_params_arguments_and_oversized_frames(self):
        k = self.kernel("mcp-hardening.sqlite")

        # List params and non-dict arguments return -32602 instead of raising AttributeError
        r1 = handle(
            k, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ["bad"]}
        )
        self.assertEqual(r1["error"]["code"], -32602)

        r2 = handle(
            k,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "line.execute", "arguments": [1]},
            },
        )
        self.assertEqual(r2["error"]["code"], -32602)

        r3 = handle(
            k,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "line.execute",
                    "arguments": {"line": "x" * (MAX_LINE_CHARS + 1)},
                },
            },
        )
        self.assertEqual(r3["error"]["code"], -32602)

        r4 = handle(k, {"jsonrpc": "1.0", "id": 4, "method": "ping"})
        self.assertEqual(r4["error"]["code"], -32600)

        # JSON-RPC 2.0 permits String, Number (including finite floats), or explicit Null IDs, while rejecting bool/array/object IDs
        self.assertEqual(
            handle(k, {"jsonrpc": "2.0", "id": None, "method": "ping"}),
            {"jsonrpc": "2.0", "id": None, "result": {}},
        )
        self.assertEqual(
            handle(k, {"jsonrpc": "2.0", "id": 2.5, "method": "ping"}),
            {"jsonrpc": "2.0", "id": 2.5, "result": {}},
        )
        self.assertIsNone(
            handle(k, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        for bad_id in (True, False, [1], {"id": 1}):
            with self.subTest(bad_id=bad_id):
                rejected = handle(k, {"jsonrpc": "2.0", "id": bad_id, "method": "ping"})
                self.assertEqual(
                    (rejected["id"], rejected["error"]["code"]), (None, -32600)
                )

        out = io.StringIO()
        oversized = ("x" * (MAX_STDIO_FRAME_CHARS + 10)) + "\n"
        nan_frame = '{"jsonrpc":"2.0","id":5,"method":"ping","params":{"v":NaN}}\n'
        serve(k, io.StringIO(oversized + nan_frame), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["error"]["code"] for r in replies], [-32600, -32700])

    def test_grpc_decode_line_rejects_malformed_and_overlong_varints_and_supports_ipv6_loopback(
        self,
    ):
        for malformed in (
            b"\x80",  # truncated key varint
            b"\x0a\x80",  # truncated length varint
            (b"\x80" * 11) + b"\x01",  # 77-bit varint overflow
            b"\x00\x01",  # field number 0
            b"\x09\x01\x02\x03",  # truncated fixed64
            b"\x0d\x01\x02",  # truncated fixed32
            b"\x0a\x05abc",  # truncated length-delimited payload
        ):
            with self.subTest(malformed), self.assertRaises(ValueError):
                decode_line(malformed)

        k = self.kernel("grpc-ipv6.sqlite")
        server = make_grpc(k, Authenticator(), "::1", 0)
        if server.bound_port > 0:
            server.start()
            self.addCleanup(server.stop, None)
            with grpc.insecure_channel(f"[::1]:{server.bound_port}") as channel:
                execute = channel.unary_unary(
                    f"/{SERVICE}/Execute",
                    request_serializer=encode_line,
                    response_deserializer=decode_line,
                )
                reply = execute(
                    'resource.read: urn:uuid:99999999-9999-4999-8999-999999999999 {"requestId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}',
                    timeout=5,
                )
                self.assertTrue(reply.startswith("error:"))

    def test_store_bounds_batch_history_and_validates_init_budgets(self):
        with self.assertRaises(ValueError):
            Store(self.root / "bad1.sqlite", commit_window=-0.1)
        with self.assertRaises(ValueError):
            Store(self.root / "bad2.sqlite", max_batch=0)

        store = Store(self.root / "bounded.sqlite", commit_window=None)
        self.addCleanup(store.close)
        self.assertEqual(store.batches.maxlen, MAX_BATCH_HISTORY)

    def test_ticket_007_parent_symlinks_bounded_stdio_surrogates_and_duplicate_headers(
        self,
    ):
        digest = hashlib.sha256(b"beta-cred").hexdigest()
        real_dir = self.root / "real_dir"
        real_dir.mkdir()
        real_auth = real_dir / "tokens.json"
        real_auth.write_text(
            json.dumps({digest: ["data:resource.read"]}), encoding="utf-8"
        )

        sym_dir = self.root / "sym_dir"
        os.symlink(real_dir, sym_dir)
        for bad_path in (
            sym_dir / "tokens.json",
            Path(str(sym_dir) + "/../real_dir/tokens.json"),
            str(real_auth) + "\x00evil",
        ):
            with self.subTest(bad_path=str(bad_path)), self.assertRaises(ValueError):
                Authenticator(bad_path)

        strict_auth = Authenticator(real_auth)
        with self.assertRaises(AuthError):
            strict_auth.scopes("Bearer \ud800")

        k = self.kernel("ticket-007.sqlite")
        self.assertEqual(k.execute(123).kind, "violation")
        self.assertEqual(
            k.execute('resource.read: urn:x:y {"a":"\ud800"}').kind, "violation"
        )

        # Real UTF-8 writer proves lone surrogates in JSON-RPC escapes never crash serve() with UnicodeEncodeError
        raw_out = io.BytesIO()
        utf8_writer = io.TextIOWrapper(raw_out, encoding="utf-8", write_through=True)
        frames = (
            ("z" * (MAX_STDIO_FRAME_CHARS * 2 + 17))
            + "\n"
            + '{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n'
            + '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"line.execute","arguments":{"line":"\\ud800"}}}\n'
            + '{"jsonrpc":"2.0","id":8,"method":"ping"}\n'
        )
        serve(k, io.StringIO(frames), utf8_writer)
        decoded_replies = [
            json.loads(line) for line in raw_out.getvalue().decode("utf-8").splitlines()
        ]
        self.assertEqual(
            [
                (r.get("id"), r.get("error", {}).get("code"), "result" in r)
                for r in decoded_replies
            ],
            [
                (None, -32600, False),
                (None, -32600, False),
                (7, -32602, False),
                (8, None, True),
            ],
        )

        # Duplicate Content-Length HTTP smuggling rejection
        rest_srv = make_rest(k, strict_auth, "127.0.0.1", 0)
        threading.Thread(target=rest_srv.serve_forever, daemon=True).start()
        self.addCleanup(rest_srv.server_close)
        self.addCleanup(rest_srv.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", rest_srv.server_port, timeout=5)
        try:
            conn.putrequest("POST", "/v2/line")
            conn.putheader("Content-Type", "text/plain")
            conn.putheader("Authorization", "Bearer beta-cred")
            conn.putheader("Content-Length", "2")
            conn.putheader("Content-Length", "2")
            conn.endheaders()
            conn.send(b"{}")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400)
            self.assertIn(
                "Multiple Content-Length",
                json.loads(resp.read().decode("utf-8"))["error"],
            )
        finally:
            conn.close()

        # Duplicate gRPC authorization metadata rejection
        grpc_srv = make_grpc(k, strict_auth, "127.0.0.1", 0)
        grpc_srv.start()
        self.addCleanup(grpc_srv.stop, None)
        with grpc.insecure_channel(f"127.0.0.1:{grpc_srv.bound_port}") as channel:
            execute = channel.unary_unary(
                f"/{SERVICE}/Execute",
                request_serializer=encode_line,
                response_deserializer=decode_line,
            )
            with self.assertRaises(grpc.RpcError) as caught:
                execute(
                    'resource.read: urn:uuid:99999999-9999-4999-8999-999999999999 {"requestId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}',
                    metadata=(
                        ("authorization", "Bearer beta-cred"),
                        ("authorization", "Bearer beta-cred"),
                    ),
                    timeout=5,
                )
            self.assertEqual(caught.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

        # Bounded CLI stdin execution
        valid_read = 'resource.read: urn:uuid:99999999-9999-4999-8999-999999999999 {"requestId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}'
        oversized_stdin = io.StringIO(
            ("q" * (MAX_STDIN_LINE_CHARS * 2 + 5)) + "\n" + valid_read + "\n"
        )
        cli_out, cli_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(cli_out), contextlib.redirect_stderr(cli_err):
            self.assertEqual(_exec_stdin(k, oversized_stdin), 2)
        self.assertIn("65536", cli_err.getvalue())
        self.assertTrue(cli_out.getvalue().startswith("error:"))


if __name__ == "__main__":
    unittest.main()
