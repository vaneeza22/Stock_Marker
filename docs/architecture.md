# Architecture

See `architecture.png` / `architecture.svg` for the AWS-style diagram (numbered flow below matches it).

## Four cooperating layers (from the brief)

| Layer | Responsibility | Meridian implementation |
|---|---|---|
| **Harness** | Orchestration: instructions, context, state, policy, evaluation, audit | `Harness.run` — one audited pipeline per request |
| **Sandbox** | Isolated execution of generated code | `Sandbox` (local rlimit process / Docker `--network none`) |
| **MCP** | Standard access to tools & context | 3 servers, `initialize / tools/list / tools/call / resources/*` |
| **PTC** | Multi-step logic expressed as code, not one-off calls | Planner emits a Python program; `tools.map` fans out; results stay in the sandbox |

## Request flow (numbers match the diagram)

1. Browser loads the dashboard (CloudFront → S3) and calls the API with a Cognito JWT (role claim → `viewer | analyst | pm`).
2. **ALB → API service (FastAPI).** `POST /api/runs` creates a run row and enqueues `meridian.run_analysis(run_id)`.
3. **Redis (ElastiCache)** is the Celery broker; `acks_late` + `prefetch=1` so crashed workers are redelivered and long analyses don't starve others.
4. **Worker** loads the session context (RDS) and starts the **harness**: request policy → context assembly → plan.
5. **Planner** (LLM via Anthropic API, or the offline template planner) returns a *PTC program*. A static AST validator checks it.
6. The program runs in the **sandbox**. Every `tools.*` call is sent over the stdio bridge back to the harness, which applies **tool policy** (role, data scope, call budget, HITL for sensitive tools), quarantines the output, and routes it via the **MCP client** to the `market`, `analytics` or `portfolio` server.
7. `market` reaches **Nasdaq** (egress through NAT) with a circuit breaker and simulator fallback; every payload carries provenance.
8. Sandbox emits charts/tables/metrics/signals. On error the harness runs the **self-debug loop** (≤ N rounds, then a safe template).
9. Signals feed the **Bull / Bear / Risk debate** → Decision Cards. The explanation is generated with assumptions, provenance and caveats.
10. Progress events + final result are written to **RDS/S3** (and every step to the hash-chained **audit log**, archived to an S3 bucket with Object Lock).
11. The UI follows progress over **SSE** (`/api/runs/{id}/stream`) and renders artifacts with its own SVG chart engine.
12. A PM may *request* a paper trade from a Decision Card → pending approval → **human approves** in the UI → paper fill. No code path creates a real order.

## Context management

```
render() = pinned(system rules, user constraints) + rolling summary + recent turns + tool-result digests
compact() when used > 85% of budget, until <= 65%:
   1. offload oversized unpinned items -> store full text under ref://ctx/…, keep a digest
   2. fold the oldest turns into one summary (extractive; LLM-assisted when available)
   3. drop lowest-priority items (never pinned items or the latest exchange)
```
PTC is the biggest context win: the 20+ raw tool payloads of a screen (~40–200k tokens) never enter the window; only the compact digest does. The UI shows this as *“N raw tokens kept out of context.”*

## Background processing

* `meridian.run_analysis` — bound task, `autoretry_for=(TransientError,)`, exponential backoff + jitter, `max_retries=3`.
* Progress (`queued → running → completed|failed`, percentage, current stage) and every event are persisted by the job runner; the result-backend is not load-bearing.
* Idempotent: re-delivered tasks for completed runs are no-ops.
* `meridian.warm_cache` (Celery Beat, every 5 min) pre-fetches the universe.
* Scale-out signal: queue depth (Redis list length) → ECS service auto-scaling on workers.

## Data model (SQLite locally / PostgreSQL on RDS)

`runs(id, session_id, user, role, prompt, status, stage, progress, attempt, result_json, error)` ·
`events(run_id, seq, type, label, data_json)` · `approvals(...)` · `holdings(...)` · `sessions(id, context_json)`.
Audit log: JSONL → S3 (Object Lock, compliance mode).

## AWS mapping

| Concern | Service |
|---|---|
| Static UI + edge | S3 + CloudFront + WAF |
| AuthN/Z | Cognito (JWT → role) |
| API | ECS Fargate (FastAPI) behind ALB |
| Queue / broker | ElastiCache Redis |
| Workers + sandbox | ECS on EC2 (needs a container runtime to launch sandbox containers; gVisor/Firecracker optional) in private subnets |
| State | RDS PostgreSQL; S3 for artifacts and audit archive |
| Secrets | Secrets Manager (API keys) |
| Egress | NAT Gateway → Nasdaq, Anthropic API. **Sandbox subnet has no route out.** |
| Observability | CloudWatch Logs/Metrics/Alarms, X-Ray; queue-depth and failure-rate alarms |
| CI/CD | GitHub Actions → ECR → ECS rolling deploy |
