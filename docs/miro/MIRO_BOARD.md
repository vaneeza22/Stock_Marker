# Meridian — Miro board content (Great tier)

Paste each section into a Miro frame (or use Miro's "Create from text"). Colour legend and links below are part of the board.

## Status legend (sticky colours)
| Colour | Meaning |
|---|---|
| Green | Built and tested |
| Yellow | Built, needs verification (live Nasdaq, Docker sandbox, LLM planner) |
| Grey | Roadmap |
| Red border | Human-review checkpoint (HITL) |

## Frame 1 — Research dump
- Problem: analysts juggle charts, filings, spreadsheets; AI answers lack provenance.
- Competitive gaps: chat tools lack audit trails; terminals lack explanation; neither gate trade actions.
- Data: Nasdaq public endpoints (unofficial) for prototype; licensed feed in production.
- Risks: hallucinated figures, prompt injection in tool output, unsafe generated code, unauthorised trades.

## Frame 2 — Personas
1. **Priya, Portfolio Manager** — wants ideas fast, must approve every trade, needs to defend decisions.
2. **Omar, Analyst** — wants indicators, comparisons, what-ifs; no approval rights.
3. **Lena, Risk/Compliance** — wants audit trail, data lineage, limits.

## Frame 3 — Pain points → opportunities
| Pain | Opportunity | Jira |
|---|---|---|
| Hours assembling analysis | One-question agent run | MER-104 |
| Cannot trust AI numbers | Provenance on every figure | MER-402 |
| Fear of autonomous trading | Approval gate, paper book | MER-105 |
| Need evidence for audits | Hash-chained log | MER-206 |

## Frame 4 — User journeys
**Idea generation (Priya):** open watchlist → ask copilot → watch timeline → read decision card → [HITL: review debate and caveats] → propose paper trade → [HITL: approve] → audit entry.
**Deep dive (Omar):** pick symbol → toggle indicators → compare peers → run what-if → export chart.
**Review (Lena):** open audit trail → verify chain → inspect run's tool calls, timestamps, errors.

## Frame 5 — Wireframes (each component linked to its integration)
| Wireframe component | Backing MCP server / integration | Jira | Status |
|---|---|---|---|
| Watchlist table | market.quote, analytics.snapshot | MER-101 | Green |
| Candle chart + indicator toggles | market.history, analytics.indicators | MER-102 | Green |
| Fundamentals card | market.fundamentals | MER-102 | Green |
| Agent canvas (charts/tables) | PTC program via sandbox bridge | MER-103 | Green |
| Decision card + debate | Bull/Bear/Risk agents, optional Anthropic API | MER-103 | Yellow (LLM) |
| Copilot timeline + context meter | SSE /api/runs/{id}/stream, context manager | MER-106 | Green |
| Approvals queue | portfolio.propose_trade (HITL) | MER-105 | Green |
| Audit trail | /api/audit/verify | MER-206 | Green |
| Live quotes | Nasdaq provider | MER-401 | Yellow |

## Frame 6 — System flow
Browser → CloudFront → ALB → FastAPI → Redis queue → Celery worker → Harness (policy → context → plan → AST validate → sandbox ⇄ MCP bridge → debate → decision card) → RDS / S3 / audit. External: Nasdaq data, Anthropic API via NAT only. See `docs/architecture.png`.

## Frame 7 — Human-review checkpoints
1. Before any trade: pm explicitly approves in the Approvals tab.
2. When data is simulated or stale: card shows a banner; PM acknowledges.
3. When a run was quarantined for injection: reviewer inspects audit entry.
