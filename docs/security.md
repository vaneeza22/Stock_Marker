# Security & safety model

## Principles
1. **Tool output is data, never instructions.** Instruction-like strings are redacted (`quarantine`) and audited.
2. **The model never gets more authority than the user's role.** Policy is enforced in the harness at the tool bridge, not in the prompt.
3. **No real-world financial action exists.** The only mutating tool (`portfolio.propose_trade`) creates a *pending approval*; only `POST /api/approvals/{id}/decide` by role `pm` fills it — against a paper book that cannot go short.
4. **Everything is attributable.** Hash-chained audit: request, policy decision, plan + code, every tool call (args, latency, payload hash), sandbox result, repair, approval.

## Policy matrix

| Role | Data scope | Tools | Budget | Trades |
|---|---|---|---|---|
| viewer | universe only | read-only | 30 calls | ✗ |
| analyst | any valid ticker | read-only | 80 calls | ✗ |
| pm | any valid ticker | + `propose_trade` (HITL) | 120 calls | request only; approval is a separate human step |

## Sandbox — layers, and the honest limits
| Layer | Local backend | Docker backend |
|---|---|---|
| AST pre-flight (imports allow-list, no dunder/`open`/`eval`/file writers) | ✓ | ✓ |
| Stripped builtins, safe `__import__`, `getattr` disabled | ✓ | ✓ |
| Network | socket monkey-patch (best effort) | `--network none` (kernel-enforced) |
| CPU / memory / files / procs | `RLIMIT_CPU/AS/FSIZE/NPROC/NOFILE` | cgroups (`--memory`, `--cpus`, `--pids-limit`) |
| Filesystem | cwd temp dir, FSIZE=0 | `--read-only`, tmpfs 16 MB, non-root, `--cap-drop ALL` |
| Wall clock | parent kills the process group | same |
| Env | scrubbed (no secrets) | none passed |

**The local backend is for development and CI. It is not a hard isolation boundary** (a determined attacker with arbitrary Python could still read files the process user can read). Production must use the Docker backend, ideally with gVisor/Firecracker, on hosts with no credentials. Secrets are never present in the sandbox environment.

## Threats considered (tests in `tests/`)
| Threat | Control | Test |
|---|---|---|
| Model writes `import os` / `open()` / dunder escapes | AST validator + runtime builtins | `test_validator_blocks`, `test_runtime_defence_in_depth_without_validator` |
| Infinite loop / memory bomb | wall-clock + rlimits | `test_sandbox_wall_clock_timeout`, `test_sandbox_memory_limit` |
| Prompt injection via data feed | quarantine + audit | `test_prompt_injection_in_tool_output_is_redacted` |
| Privilege escalation (viewer → trade) | role check at bridge | `test_viewer_cannot_propose_and_denial_is_audited` |
| Out-of-scope data | scope rule | `test_viewer_scope_denies_out_of_universe_symbol` |
| Log tampering | hash chain | `test_audit_chain_detects_tampering` |
| Runaway tool use | per-run call budget | `test_policy_decisions` |
| Duplicate delivery | idempotent task | `test_celery_task_eager_executes_and_is_idempotent` |

## Known gaps / roadmap
* Auth in the demo is a header (`X-Role`); production uses Cognito JWT claims.
* Audit log is file-based; production ships to S3 Object Lock and signs checkpoints with KMS.
* Rate limiting per user, request signing for MCP-over-HTTP, and SBOM/dependency scanning in CI.
