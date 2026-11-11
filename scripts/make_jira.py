"""Generate the Jira backlog pack (CSV for import + markdown) from one source of truth."""
import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "jira"
EPICS = [
    ("MER-1", "Portfolio Manager Trading Workspace", "PM-facing experience: dashboards, copilot, decision cards, approvals."),
    ("MER-2", "Agentic Infrastructure & MCP Integration", "Harness, context management, PTC, MCP servers, policy."),
    ("MER-3", "Sandbox & Safe Execution", "Isolated Python execution, validation, self-debug loop."),
    ("MER-4", "Data Platform (Nasdaq) & Provenance", "Live Nasdaq provider, fallback, per-field provenance."),
    ("MER-5", "Async Jobs & Cloud Deployment", "Celery/Redis workers, progress, retries, AWS, CI/CD."),
    ("MER-6", "Product Discovery & Delivery Ops", "Miro research/wireframes, Jira hygiene, presentation."),
]
# key, epic, title, owner role, points, status, acceptance criteria, evidence
S = [
 ("MER-101","MER-1","Market overview and watchlist dashboard","Frontend Eng",5,"Done","Watchlist shows price, change, trend, tech score for the universe; every number carries a data-source label.","web/index.html; tests/test_api_jobs.py"),
 ("MER-102","MER-1","Symbol workspace with candles and indicator toggles","Frontend Eng",8,"Done","Candles + SMA/EMA/Bollinger/RSI/MACD/volume render from API data; fundamentals card with valuation; simulated data is labelled.","web/index.html; meridian/analytics/technical.py"),
 ("MER-103","MER-1","Agent canvas: charts, tables, decision cards","Frontend Eng",8,"Done","Agent output renders as tiles, charts and cards; Bull/Bear/Risk debate is collapsible; assumptions and caveats visible.","web/index.html; meridian/harness/agents.py"),
 ("MER-104","MER-1","Enable Portfolio Manager Trading Idea Generator via Agentic Loop","Tech Lead",13,"Done",
  "Validates request and data scope; uses registered tools only; runs code in sandbox with time/memory/network limits; records tool calls, data timestamps, calculations, errors, outputs; states assumptions, provenance and risk caveats; no trade without separate explicit approval.",
  "meridian/harness/core.py; tests/test_harness.py"),
 ("MER-105","MER-1","Human approval workflow for paper trades","Backend Eng",5,"Done","propose_trade creates a pending approval; only pm role can approve; approval paper-fills; paper book cannot go short; no real orders.","meridian/jobs/store.py; tests/test_api_jobs.py"),
 ("MER-106","MER-1","Copilot chat with live timeline and context meter","Frontend Eng",5,"Done","Run progress streams via SSE; context usage meter shows budget, offloaded refs and tokens kept out of context.","web/index.html; /api/runs/{id}/stream"),
 ("MER-201","MER-2","Harness pipeline (policy, context, plan, run, debate, card)","Tech Lead",13,"Done","Each stage emits audited events; failures surface as typed errors; transient errors are retriable.","meridian/harness/core.py"),
 ("MER-202","MER-2","Context management (budget, pin, offload, summarise)","AI Eng",8,"Done","Context never exceeds budget; large payloads offloaded to ref://ctx; lowest-priority items dropped; state persists across workers.","meridian/harness/context.py"),
 ("MER-203","MER-2","MCP servers: market, analytics, portfolio","Backend Eng",8,"Done","JSON-RPC 2.0 tools/list + tools/call; schema validation; annotations (readOnlyHint, sensitivity); in-proc, stdio and HTTP transports.","meridian/mcp/; tests/test_mcp_sandbox.py"),
 ("MER-204","MER-2","Programmatic tool calling planner (templates + optional LLM)","AI Eng",13,"Done","Planner emits one Python program calling tools.<server>_<tool>; parallel fan-out via tools.map; offline template planner works without an API key.","meridian/harness/planner.py"),
 ("MER-205","MER-2","Policy engine and prompt-injection quarantine","Security Eng",8,"Done","Roles viewer/analyst/pm; data scope and call budgets enforced; tool results flagged as data, injection patterns quarantined.","meridian/harness/policy.py"),
 ("MER-206","MER-2","Tamper-evident audit log","Security Eng",5,"Done","Hash-chained JSONL; /api/audit/verify detects any edit; concurrent writers safe.","meridian/harness/audit.py"),
 ("MER-301","MER-3","AST validator and restricted runner","Security Eng",8,"Done","Disallowed imports/builtins/attributes rejected before execution; runner strips builtins and blocks sockets.","meridian/sandbox/validator.py; runner.py"),
 ("MER-302","MER-3","Resource-limited sandbox executor","Backend Eng",8,"Done","CPU, memory, file size, process and wall-time limits enforced; deadline extends only for tool latency.","meridian/sandbox/executor.py"),
 ("MER-303","MER-3","Self-debug and repair loop","AI Eng",8,"Done","On failure the planner repairs up to 2 times then falls back to a template; timeout/memory failures retry lighter.","tests/test_harness.py"),
 ("MER-304","MER-3","Docker sandbox backend (network none, read-only)","DevOps",5,"In Review","Container runs with --network none --read-only --cap-drop ALL; CI isolation smoke test passes. Not run in build environment.",".github/workflows/ci.yml"),
 ("MER-401","MER-4","Nasdaq provider","Data Eng",8,"In Review","Parses api.nasdaq.com quote/history/fundamentals responses; fixture-tested; live responses to be verified on a networked host.","meridian/data/providers.py"),
 ("MER-402","MER-4","Synthetic provider and fallback with circuit breaker","Data Eng",5,"Done","Auto provider falls back when Nasdaq fails; simulated data always labelled; per-field provenance returned.","meridian/data/providers.py"),
 ("MER-403","MER-4","Technical and fundamental analytics library","Quant Eng",8,"Done","Indicators match reference formulas; patterns, trend, support/resistance, valuation scoring covered by tests.","meridian/analytics/; tests/test_analytics_data.py"),
 ("MER-404","MER-4","Monte-Carlo, portfolio stats, backtest","Quant Eng",5,"Done","Fan-chart projections, what-if scenarios, RSI backtest return reproducible given a seed.","meridian/analytics/simulation.py"),
 ("MER-501","MER-5","Celery workers with retries and progress","Backend Eng",8,"Done","acks_late, autoretry with backoff on TransientError; progress persisted; idempotent redelivery; verified against real Redis.","meridian/jobs/tasks.py; scripts/smoke_celery.py"),
 ("MER-502","MER-5","FastAPI service with SSE","Backend Eng",5,"Done","POST /api/runs returns 202; GET and SSE stream expose progress and results.","meridian/api/app.py"),
 ("MER-503","MER-5","Dockerfiles and compose stack","DevOps",3,"Done","docker compose up runs redis, api, worker, beat.","docker-compose.yml"),
 ("MER-504","MER-5","GitHub Actions CI","DevOps",5,"Done","Lint, tests, Celery integration with Redis, docker build on every PR.",".github/workflows/ci.yml"),
 ("MER-505","MER-5","AWS infrastructure as code","DevOps",8,"To Do","Terraform/CDK for VPC, ECS, ElastiCache, RDS, ALB, S3, KMS per architecture diagram.","docs/architecture.png"),
 ("MER-601","MER-6","Miro board: research, journeys, wireframes, system flow","Product Manager",8,"Done","Board meets the Great tier: every wireframe component links to its MCP server/integration, HITL checkpoints, status legend.","docs/miro/"),
 ("MER-602","MER-6","Jira board with epics, stories, owners, criteria","Product Manager",3,"Done","All stories carry owner, points, acceptance criteria.","docs/jira/"),
 ("MER-603","MER-6","Brief presentation","Product Manager",3,"Done","Covers problem, features, architecture, demo.","presentation"),
]
OUT.mkdir(parents=True, exist_ok=True)
with open(OUT / "meridian_backlog.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Issue Key", "Issue Type", "Summary", "Epic Link", "Assignee Role", "Story Points", "Status", "Acceptance Criteria", "Evidence"])
    for k, t, d in EPICS:
        w.writerow([k, "Epic", t, "", "", "", "In Progress", d, ""])
    for r in S:
        w.writerow([r[0], "Story", r[2], r[1], r[3], r[4], r[5], r[6], r[7]])
md = ["# Meridian — Jira backlog", "", "Import `meridian_backlog.csv` (Jira → Import issues from CSV) or recreate from this table.", ""]
for k, t, d in EPICS:
    items = [r for r in S if r[1] == k]
    md += [f"## {k} · {t}", d, "", "| Key | Story | Owner | SP | Status |", "|---|---|---|---|---|"]
    md += [f"| {r[0]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in items]
    md += [""]
    for r in items:
        md += [f"**{r[0]} — {r[2]}**  ", f"*Acceptance:* {r[6]}  ", f"*Evidence:* `{r[7]}`", ""]
(OUT / "BACKLOG.md").write_text("\n".join(md))
owners = {}
for r in S:
    owners.setdefault(r[3], []).append(r)
c = ["# Contributions", "", "Roles map one-to-one to Jira owners. Replace role names with team members' GitHub handles.", "",
     "| Role | Stories | Points |", "|---|---|---|"]
for o, rs in sorted(owners.items()):
    c.append(f"| {o} | {', '.join(x[0] for x in rs)} | {sum(x[4] for x in rs)} |")
c += ["", "Each PR references its Jira key, uses `.github/PULL_REQUEST_TEMPLATE.md`, and must pass CI (ruff, pytest, Celery integration, docker build)."]
Path(OUT.parent / "CONTRIBUTIONS.md").write_text("\n".join(c) + "\n")
print(len(S), "stories", sum(r[4] for r in S), "points")
