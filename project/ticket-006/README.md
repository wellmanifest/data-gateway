# Ticket 006: Preserve null and finite numeric JSON-RPC 2.0 request IDs in MCP transport

- **ID**: ticket-006
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Goal and scope

Resolve the `ticket-005` Validator advisory on `data_gateway/mcp.py`:
- Accept JSON-RPC 2.0 protocol-valid `id` values (`str`, finite `int`/`float`, or explicit `None` when `"id"` is present in the request object) while continuing to treat omitted `"id"` members as notifications and rejecting `bool`, `list`, `dict`, and non-finite `float` IDs with `-32600`.
- Add regression assertions in `tests/test_hardening.py`.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (regression follow-up to `ticket-005` Validator review).
- [x] AC-02: `ruff check`, `make check`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
