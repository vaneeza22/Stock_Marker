# Contributing

## Flow
1. Pick a Jira story (`MER-nnn`) — acceptance criteria are in the ticket.
2. Branch from `main`: `feat/MER-123-short-name`, `fix/MER-456-…`, `docs/…`.
3. Small, reviewable commits — Conventional Commits, ticket key in the subject: `feat(harness): offload oversized context items (MER-118)`.
4. Open a PR using the template; link the Jira key and attach evidence (test output / screenshot / audit snippet).
5. CI must be green (`ruff`, `pytest`, Celery integration, Docker build). One approving review from a CODEOWNER.
6. Squash-merge. The Jira ticket moves to *Done* only when every acceptance criterion is demonstrably met.

## Definition of done
- [ ] Acceptance criteria met and demoed
- [ ] Unit tests for new logic; negative tests for security-relevant paths
- [ ] No new network or filesystem access in the sandbox without an ADR
- [ ] Audit events added for any new tool/side-effect
- [ ] Docs updated (`docs/`, README table if a capability changed)
- [ ] Data provenance preserved on any new payload

## Local checks
```bash
ruff check . && pytest
```
