# Ticket 004: Gateway performance fixes and group commit

- **ID**: ticket-004
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

Application slice of the measured gateway improvements; depends on ticket-003
(fastjsonschema dependency, `make bench`, report `docs/analysis/gateway-benchmark.md`).

- Queries commit their audit with WAL `synchronous=NORMAL`; commands stay `FULL`.
- Compiled schema validators (fastjsonschema), pinned equivalent to Draft 2020-12
  by `tests/test_schema_equivalence.py`.
- One parse per request for classification and input hash.
- Group commit in `Store.transaction`:
  - each command runs in its own SAVEPOINT;
  - the reply goes out only after COMMIT;
  - a lone command commits at once;
  - `commit_window=None` disables grouping.

  Tests: `tests/test_group_commit.py`.
- `benchmarks/bench.py`: A/B against an ad-hoc SQLite baseline, with regression gates.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (owner request 2026-10-13, "wykonaj").
- [ ] AC-02: `make test` passes, including the equivalence and group commit tests.
- [ ] AC-03: `make bench BENCH_DIR=<disk dir>` passes every regression gate.

## Tracking boundary

This directory contains the minimal reviewed intent.
