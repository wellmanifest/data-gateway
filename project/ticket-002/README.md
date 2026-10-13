# Ticket 002: Assign gateway source paths to workstreams

- **ID**: ticket-002
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

After governance adoption (ticket-001), most tracked gateway paths are owned by
no workstream, so no product ticket can be allocated for them. This ticket
extends only the target-owned `.governance/manifest.json`:

- application: `data_gateway/**`, `benchmarks/**`;
- integration: `requirements*.txt`, `upstream.lock.json`, `Makefile`, `tools/**`,
  `errors/**`, `logs-error-catalog.v1.json`;
- infrastructure: `.github/workflows/ci.yml`.

It is a prerequisite for the performance fixes and benchmark the owner asked
for on 2026-10-13 ("stworz też benchmark … dopracuj rozwiązanie").

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (owner request 2026-10-13).
- [ ] AC-02: Every tracked path has exactly one owner; `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent.
