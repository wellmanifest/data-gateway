# Ticket 003: Benchmark dependencies, make bench and benchmark report

- **ID**: ticket-003
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

Integration slice of the gateway performance work the owner asked for on
2026-10-13 ("stworz też benchmark … dopracuj rozwiązanie", then "wykonaj"):

- `fastjsonschema==2.21.1` runtime dependency for compiled schema validation.
  `jsonschema` stays until the application slice switches the kernel and keeps it
  as the test oracle.
- `make bench`: runs `benchmarks/bench.py --check --clients 8`. The script and
  the code changes land in the dependent application ticket.
- `docs/analysis/gateway-benchmark.md` (status `proposed`), indexed in
  `docs/README.md`: method, before/after numbers, group commit, remaining
  regressions and recommendations.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (owner request 2026-10-13).
- [ ] AC-02: `./project/governance-check.sh`, `make test` and `make docs-check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent.
