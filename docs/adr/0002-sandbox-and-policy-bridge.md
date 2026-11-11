# ADR-0002: Sandbox with a policy-checked tool bridge

**Status:** accepted

**Decision.** Sandbox code has *no* direct access to the network, files or secrets. The only way out is a JSON-over-stdio bridge to the harness, which applies role/scope/budget policy, quarantines results, and then calls MCP. Local backend (rlimits) for dev/CI; Docker `--network none` for production.

**Alternatives.** In-process `exec` with restricted globals (rejected: not a boundary); one Lambda per run (rejected: bidirectional tool bridge is awkward and cold starts hurt interactivity).

**Consequences.** Every effect is observable and auditable. Local backend is explicitly *not* a security boundary (documented in `docs/security.md`).
