# Ticket 007: Harden auth symlink-parent traversal, bounded stdio streaming, UTF-8 surrogates, and duplicate header smuggling

- **ID**: ticket-007
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-12

## Session authorization

- `SESSION_EXECUTION_AUTHORIZATION`: Autonomous execution, testing, and protected publication requested by the repository owner.

## Goal and scope

Harden file-boundary, stdio-memory, UTF-8 surrogate, and duplicate-header invariants across `data_gateway`:

1. `data_gateway/auth.py`: Reject symlinked parent/ancestor path segments before `..` collapse (`sym_dir/tokens.json`, `sym_dir/../real_dir/tokens.json`), reject NUL-byte paths, verify `(st_dev, st_ino)` parity between `os.lstat` and `os.fstat`, and fail closed with `AuthError` on lone UTF-16 surrogates in `Authorization` headers.
2. `data_gateway/kernel.py` & `data_gateway/mcp.py`: Bound MCP stdio line reads (`readline(MAX_STDIO_FRAME_CHARS + 1)` with chunked remainder drain) so missing newlines cannot exhaust memory, and reject non-`str` or lone UTF-16 surrogate inputs (`\ud800`..`\udfff`) cleanly instead of raising `UnicodeEncodeError` on UTF-8 `TextIOWrapper` writes or input hashing.
3. `data_gateway/rest.py`, `data_gateway/grpc_server.py`, & `data_gateway/cli.py`: Reject multiple `Content-Length` headers in `POST /v2/line` (RFC 9112 §6.3), reject duplicate `authorization` gRPC metadata entries with `UNAUTHENTICATED`, and bound CLI `exec` stdin line reads (`MAX_STDIN_LINE_CHARS = 65536`).
4. `tests/test_hardening.py`: Add end-to-end adversarial regression coverage for all above vectors while keeping every module strictly `< 500` lines.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (autonomous hardening and testing requested by repository owner).
- [x] AC-02: `ruff check --no-cache`, `make check` (`make test` + `make docs-check`), `./project/governance-check.sh --base origin/main`, and `wellman check` pass with 0 errors and all touched Python modules remain `< 500` lines after `ruff format`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
