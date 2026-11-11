# ADR-0004: Hash-chained audit log

**Status:** accepted

**Decision.** Append-only JSONL; each record stores `prev` and `hash = sha256(prev + canonical(body))`; appends are serialised with `flock` so API and workers share one chain. `verify()` walks the chain. Production archives to S3 Object Lock.

**Consequences.** Edits, deletions and re-ordering are detectable. It is tamper-*evident*, not tamper-proof: a full rewrite of the file is only caught if a checkpoint hash is stored elsewhere (roadmap: KMS-signed checkpoints).
