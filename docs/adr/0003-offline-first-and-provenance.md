# ADR-0003: Offline-first planner and provenance on every payload

**Status:** accepted

**Context.** Live feeds and LLM keys are not always available (CI, demos, outages); Nasdaq's public endpoints are unofficial.

**Decision.** (1) Deterministic template planner when no LLM is configured, and as the last-resort repair. (2) Provider chain Nasdaq → simulator with a circuit breaker; every payload carries `{source, simulated, as_of}` and fundamentals carry per-field sources. (3) The UI and explanation footer always state which data was used.

**Consequences.** Product always works and is testable; risk of mistaking simulated data for real is mitigated by persistent badges.
