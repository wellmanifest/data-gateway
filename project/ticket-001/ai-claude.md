# ticket-001 — agent notes (claude)

## Route

1. Fresh clone of `main` at `78b6b91` (after data-gateway #1: docs 0.6.0 pin, VERSION, CHANGELOG).
2. Untracked prerequisites `TODO.md`, `project/TICKETS.md`.
3. `create_adoption_lock.py --source-revision c6587635… --bootstrap-native-adoption --upgrade` in the primary clone, which wrote `.subactor/receipts/bootstrap-adoption.json`.
4. `work_start_check.py --allocation-check` returned `RECONCILE` / `pending-delta` with dirtyDigest `3cf2ee2c…`.
5. `./project/new-ticket.sh -w governance --path … --bootstrap-adoption-digest 3cf2ee2c…` allocated ticket-001 in its canonical worktree.
6. Same adopter `--upgrade` applied in this worktree; the file set matches the primary delta plus the ticket directory.

## Deviations recorded

- **Duplicate `TODO.md`.** Avoided by not passing `--path TODO.md`; the allocator adds it (wellmanifest/new-project#480).
- **Lease `scopeHash`.** The allocator projection lease in `.subactor/leases/` was computed before the two installer paths were added to `allowedPaths`. It is advisory local state, not a controller grant (allocator comment), and the gate does not compare it. No controller lease was issued or fabricated.
- **Unowned installer files.** The base manifest at 0.20.97 owns neither `.gitattributes` nor `new-project-branch-hygiene.yml`, which gave GOV-SCOPE-001/GOV-WORKSTREAM-003. Governance ownership was extended in the target-owned `.governance/manifest.json`, as nl-uri-dsl-llm and how-to-use-subactor did.

## Checks

Results are recorded in the PR description with the exact commands that ran.
