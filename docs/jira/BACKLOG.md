# Meridian — Jira backlog

Import `meridian_backlog.csv` (Jira → Import issues from CSV) or recreate from this table.

## MER-1 · Portfolio Manager Trading Workspace
PM-facing experience: dashboards, copilot, decision cards, approvals.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-101 | Market overview and watchlist dashboard | Frontend Eng | 5 | Done |
| MER-102 | Symbol workspace with candles and indicator toggles | Frontend Eng | 8 | Done |
| MER-103 | Agent canvas: charts, tables, decision cards | Frontend Eng | 8 | Done |
| MER-104 | Enable Portfolio Manager Trading Idea Generator via Agentic Loop | Tech Lead | 13 | Done |
| MER-105 | Human approval workflow for paper trades | Backend Eng | 5 | Done |
| MER-106 | Copilot chat with live timeline and context meter | Frontend Eng | 5 | Done |

**MER-101 — Market overview and watchlist dashboard**  
*Acceptance:* Watchlist shows price, change, trend, tech score for the universe; every number carries a data-source label.  
*Evidence:* `web/index.html; tests/test_api_jobs.py`

**MER-102 — Symbol workspace with candles and indicator toggles**  
*Acceptance:* Candles + SMA/EMA/Bollinger/RSI/MACD/volume render from API data; fundamentals card with valuation; simulated data is labelled.  
*Evidence:* `web/index.html; meridian/analytics/technical.py`

**MER-103 — Agent canvas: charts, tables, decision cards**  
*Acceptance:* Agent output renders as tiles, charts and cards; Bull/Bear/Risk debate is collapsible; assumptions and caveats visible.  
*Evidence:* `web/index.html; meridian/harness/agents.py`

**MER-104 — Enable Portfolio Manager Trading Idea Generator via Agentic Loop**  
*Acceptance:* Validates request and data scope; uses registered tools only; runs code in sandbox with time/memory/network limits; records tool calls, data timestamps, calculations, errors, outputs; states assumptions, provenance and risk caveats; no trade without separate explicit approval.  
*Evidence:* `meridian/harness/core.py; tests/test_harness.py`

**MER-105 — Human approval workflow for paper trades**  
*Acceptance:* propose_trade creates a pending approval; only pm role can approve; approval paper-fills; paper book cannot go short; no real orders.  
*Evidence:* `meridian/jobs/store.py; tests/test_api_jobs.py`

**MER-106 — Copilot chat with live timeline and context meter**  
*Acceptance:* Run progress streams via SSE; context usage meter shows budget, offloaded refs and tokens kept out of context.  
*Evidence:* `web/index.html; /api/runs/{id}/stream`

## MER-2 · Agentic Infrastructure & MCP Integration
Harness, context management, PTC, MCP servers, policy.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-201 | Harness pipeline (policy, context, plan, run, debate, card) | Tech Lead | 13 | Done |
| MER-202 | Context management (budget, pin, offload, summarise) | AI Eng | 8 | Done |
| MER-203 | MCP servers: market, analytics, portfolio | Backend Eng | 8 | Done |
| MER-204 | Programmatic tool calling planner (templates + optional LLM) | AI Eng | 13 | Done |
| MER-205 | Policy engine and prompt-injection quarantine | Security Eng | 8 | Done |
| MER-206 | Tamper-evident audit log | Security Eng | 5 | Done |

**MER-201 — Harness pipeline (policy, context, plan, run, debate, card)**  
*Acceptance:* Each stage emits audited events; failures surface as typed errors; transient errors are retriable.  
*Evidence:* `meridian/harness/core.py`

**MER-202 — Context management (budget, pin, offload, summarise)**  
*Acceptance:* Context never exceeds budget; large payloads offloaded to ref://ctx; lowest-priority items dropped; state persists across workers.  
*Evidence:* `meridian/harness/context.py`

**MER-203 — MCP servers: market, analytics, portfolio**  
*Acceptance:* JSON-RPC 2.0 tools/list + tools/call; schema validation; annotations (readOnlyHint, sensitivity); in-proc, stdio and HTTP transports.  
*Evidence:* `meridian/mcp/; tests/test_mcp_sandbox.py`

**MER-204 — Programmatic tool calling planner (templates + optional LLM)**  
*Acceptance:* Planner emits one Python program calling tools.<server>_<tool>; parallel fan-out via tools.map; offline template planner works without an API key.  
*Evidence:* `meridian/harness/planner.py`

**MER-205 — Policy engine and prompt-injection quarantine**  
*Acceptance:* Roles viewer/analyst/pm; data scope and call budgets enforced; tool results flagged as data, injection patterns quarantined.  
*Evidence:* `meridian/harness/policy.py`

**MER-206 — Tamper-evident audit log**  
*Acceptance:* Hash-chained JSONL; /api/audit/verify detects any edit; concurrent writers safe.  
*Evidence:* `meridian/harness/audit.py`

## MER-3 · Sandbox & Safe Execution
Isolated Python execution, validation, self-debug loop.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-301 | AST validator and restricted runner | Security Eng | 8 | Done |
| MER-302 | Resource-limited sandbox executor | Backend Eng | 8 | Done |
| MER-303 | Self-debug and repair loop | AI Eng | 8 | Done |
| MER-304 | Docker sandbox backend (network none, read-only) | DevOps | 5 | In Review |

**MER-301 — AST validator and restricted runner**  
*Acceptance:* Disallowed imports/builtins/attributes rejected before execution; runner strips builtins and blocks sockets.  
*Evidence:* `meridian/sandbox/validator.py; runner.py`

**MER-302 — Resource-limited sandbox executor**  
*Acceptance:* CPU, memory, file size, process and wall-time limits enforced; deadline extends only for tool latency.  
*Evidence:* `meridian/sandbox/executor.py`

**MER-303 — Self-debug and repair loop**  
*Acceptance:* On failure the planner repairs up to 2 times then falls back to a template; timeout/memory failures retry lighter.  
*Evidence:* `tests/test_harness.py`

**MER-304 — Docker sandbox backend (network none, read-only)**  
*Acceptance:* Container runs with --network none --read-only --cap-drop ALL; CI isolation smoke test passes. Not run in build environment.  
*Evidence:* `.github/workflows/ci.yml`

## MER-4 · Data Platform (Nasdaq) & Provenance
Live Nasdaq provider, fallback, per-field provenance.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-401 | Nasdaq provider | Data Eng | 8 | In Review |
| MER-402 | Synthetic provider and fallback with circuit breaker | Data Eng | 5 | Done |
| MER-403 | Technical and fundamental analytics library | Quant Eng | 8 | Done |
| MER-404 | Monte-Carlo, portfolio stats, backtest | Quant Eng | 5 | Done |

**MER-401 — Nasdaq provider**  
*Acceptance:* Parses api.nasdaq.com quote/history/fundamentals responses; fixture-tested; live responses to be verified on a networked host.  
*Evidence:* `meridian/data/providers.py`

**MER-402 — Synthetic provider and fallback with circuit breaker**  
*Acceptance:* Auto provider falls back when Nasdaq fails; simulated data always labelled; per-field provenance returned.  
*Evidence:* `meridian/data/providers.py`

**MER-403 — Technical and fundamental analytics library**  
*Acceptance:* Indicators match reference formulas; patterns, trend, support/resistance, valuation scoring covered by tests.  
*Evidence:* `meridian/analytics/; tests/test_analytics_data.py`

**MER-404 — Monte-Carlo, portfolio stats, backtest**  
*Acceptance:* Fan-chart projections, what-if scenarios, RSI backtest return reproducible given a seed.  
*Evidence:* `meridian/analytics/simulation.py`

## MER-5 · Async Jobs & Cloud Deployment
Celery/Redis workers, progress, retries, AWS, CI/CD.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-501 | Celery workers with retries and progress | Backend Eng | 8 | Done |
| MER-502 | FastAPI service with SSE | Backend Eng | 5 | Done |
| MER-503 | Dockerfiles and compose stack | DevOps | 3 | Done |
| MER-504 | GitHub Actions CI | DevOps | 5 | Done |
| MER-505 | AWS infrastructure as code | DevOps | 8 | To Do |

**MER-501 — Celery workers with retries and progress**  
*Acceptance:* acks_late, autoretry with backoff on TransientError; progress persisted; idempotent redelivery; verified against real Redis.  
*Evidence:* `meridian/jobs/tasks.py; scripts/smoke_celery.py`

**MER-502 — FastAPI service with SSE**  
*Acceptance:* POST /api/runs returns 202; GET and SSE stream expose progress and results.  
*Evidence:* `meridian/api/app.py`

**MER-503 — Dockerfiles and compose stack**  
*Acceptance:* docker compose up runs redis, api, worker, beat.  
*Evidence:* `docker-compose.yml`

**MER-504 — GitHub Actions CI**  
*Acceptance:* Lint, tests, Celery integration with Redis, docker build on every PR.  
*Evidence:* `.github/workflows/ci.yml`

**MER-505 — AWS infrastructure as code**  
*Acceptance:* Terraform/CDK for VPC, ECS, ElastiCache, RDS, ALB, S3, KMS per architecture diagram.  
*Evidence:* `docs/architecture.png`

## MER-6 · Product Discovery & Delivery Ops
Miro research/wireframes, Jira hygiene, presentation.

| Key | Story | Owner | SP | Status |
|---|---|---|---|---|
| MER-601 | Miro board: research, journeys, wireframes, system flow | Product Manager | 8 | Done |
| MER-602 | Jira board with epics, stories, owners, criteria | Product Manager | 3 | Done |
| MER-603 | Brief presentation | Product Manager | 3 | Done |

**MER-601 — Miro board: research, journeys, wireframes, system flow**  
*Acceptance:* Board meets the Great tier: every wireframe component links to its MCP server/integration, HITL checkpoints, status legend.  
*Evidence:* `docs/miro/`

**MER-602 — Jira board with epics, stories, owners, criteria**  
*Acceptance:* All stories carry owner, points, acceptance criteria.  
*Evidence:* `docs/jira/`

**MER-603 — Brief presentation**  
*Acceptance:* Covers problem, features, architecture, demo.  
*Evidence:* `presentation`
