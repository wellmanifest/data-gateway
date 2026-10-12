# Instructions for contributors and LLM agents

This is the runtime adopter of `wellmanifest/data-plane`. It owns gateway code, its `GW` error namespace and runbooks, and nothing in the standard.

- Read `docs/information/gateway.md` and `upstream.lock.json` before changes.
- Do not copy data-plane or logs code; import the pinned checkout (`make upstream`). Changing a pin means updating every digest in `upstream.lock.json`.
- Every transport must call `Kernel.execute`; transport code only carries the line and maps the outcome. Keep `tests/test_gateway.py` transport equivalence passing.
- Command effects, domain event, receipt and audit event commit in one transaction. Never write the read model without an event.
- Audit events must stay valid `wellmanifest.logs/event/v1`; never put request variables, content or tokens into audit or error lines.
- Run `make test` and `make docs-check` after changes; record which checks actually ran. Do not claim TLS, production auth or live deployment from these tests.
- Follow the repository's review and publication process; these instructions grant no merge or deploy authority.
