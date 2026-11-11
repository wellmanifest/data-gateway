# Ticket 005: Harden transport decoders, token file loading, and bounded store telemetry

- **ID**: ticket-005
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Goal and scope

Harden transport request/wire boundaries, auth mapping file safety, and long-running store batch telemetry in `data_gateway`:
- `data_gateway/auth.py`: enforce `O_NOFOLLOW | O_NONBLOCK` regular-file loading with a 1 MiB byte cap, reject duplicate keys and non-finite JSON constants, validate 64-hex SHA-256 digests and string scope lists, perform constant-time digest lookup, and block hostname/IPv4-mapped/scoped-IPv6 loopback bypasses in `require_safe_bind()`.
- `data_gateway/rest.py`: reject `Transfer-Encoding`, negative or non-digit `Content-Length` headers (`rfile.read(-1)` unbounded-read fix), and incomplete bodies; compare `Content-Type` essence case-insensitively; drain bounded bodies on early HTTP rejections and handle client disconnects cleanly.
- `data_gateway/mcp.py`: validate JSON-RPC 2.0 version/method/id, reject non-object `params` and `arguments` with `-32602` instead of raising `AttributeError`, enforce `MAX_LINE_CHARS` (`65536`) and `MAX_STDIO_FRAME_CHARS` (`262144`), and reject `NaN`/`Infinity` constants.
- `data_gateway/grpc_server.py`: bound protobuf varint shifts to 64 bits and validate truncated varints, field number `0`, and truncated `fixed32`/`fixed64` payloads with `ValueError`; bracket IPv6 hosts when binding gRPC ports.
- `data_gateway/store.py`: bound `Store.batches` with `deque(maxlen=4096)` to prevent unbounded memory growth in long-lived servers and validate `commit_window`/`max_batch` parameters.
- `tests/test_hardening.py`: adversarial regression tests covering all five modules.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (continuous hardening/testing session).
- [x] AC-02: `make test`, `make docs-check`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass with all owned modules under 500 lines.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
