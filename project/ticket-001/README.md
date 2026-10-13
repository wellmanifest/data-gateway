# Ticket 001: Adopt wellmanifest/new-project 0.20.97 governance

- **ID**: ticket-001
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-13

## Goal and scope

Install the published immutable `wellmanifest/new-project` package at
`c6587635bafb054241fd71fd22793af47acae83b` (0.20.97) through its adopter with
`--bootstrap-native-adoption`. Afterwards, data-gateway work is allocated
through tickets, and the Validator's account-level `wellmanifest` profile can
publish it. That profile requires `governance / enforce` and
`governance / remote lifecycle`.

The owner requested enrollment of data-plane and data-gateway in the
Wellmanifest fleet ("a i b", 2026-10-12) and confirmed starting the
data-gateway adoption ("tak", 2026-10-13). data-plane follows the same route in
wellmanifest/data-plane#9. This ticket covers only the governance package.

The only repository-local change beyond installer bytes extends governance
ownership in `.governance/manifest.json` to `.gitattributes` and
`.github/workflows/new-project-branch-hygiene.yml`. The package installs both,
but its base manifest assigns them to no workstream. Gateway code, tests, the
error catalog, upstream pins and docs are out of scope.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (owner "tak", 2026-10-13).
- [ ] AC-02: `create_adoption_lock.py --check` at the pinned revision reports no drift.
- [ ] AC-03: `./project/governance-check.sh` (against base `78b6b91`), `make test` and `make docs-check` pass.
- [ ] AC-04: Hosted checks pass on the PR head; publication follows the independent Validator, never the authoring agent.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
