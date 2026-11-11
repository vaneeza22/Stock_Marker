# ADR-0001: Programmatic tool calling (PTC) instead of one-call-per-turn

**Status:** accepted

**Context.** A screen over 16 names needs ~20 tool calls and returns >100k tokens of raw data. A classic loop pastes every result into the context, is slow (serial round-trips), expensive, and lets untrusted data steer the model.

**Decision.** The planner emits one Python program. Tool calls are functions (`tools.market_history(...)`, `tools.map(...)` for parallel fan-out). Raw data stays inside the sandbox; only emitted charts/tables/signals and a digest leave it.

**Consequences.** (+) >90 % context saving, parallelism, reproducible code recorded in the audit log. (−) generated code is an attack surface → AST validator, sandbox, policy-checked bridge (ADR-0002).
