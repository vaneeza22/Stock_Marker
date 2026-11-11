# Product brief — Meridian

## Problem
Portfolio managers lose time stitching together charts, fundamentals, spreadsheets and ad-hoc scripts to evaluate a trading idea — and existing AI tools make tool execution hard to control or audit. They need **one conversational surface** that returns *explained, reproducible* analysis with its **sources and assumptions**, under controls their risk team can inspect.

## Users
| Persona | Needs | Job-to-be-done |
|---|---|---|
| **Priya — Portfolio Manager** | Fast screening, sizing what-ifs, a defensible rationale | “Which oversold names deserve capital, and what could go wrong?” |
| **Omar — Research Analyst** | Deep dives on one name; back-tests; comparisons | “Show me the technical and fundamental picture and test my rule.” |
| **Lena — Risk / Compliance** | Evidence of what ran, on what data, who approved | “Prove this output came from these inputs, and nothing traded.” |

## Value proposition
*Ask in plain English → get charts, tables, a bull/bear/risk debate and an audit trail — in seconds, with provenance and a human gate on anything that matters.*

## Features (MoSCoW)
**Must** — technical analysis (candles, SMA/EMA, Bollinger, RSI, MACD, volume, trend, patterns, support/resistance) · fundamental analysis (ratios, quality/growth/valuation scoring, statements) · Python-powered what-ifs, projections (Monte-Carlo), back-tests · explanations with sources/assumptions · interactive charts/tables · harness + MCP + tool calling + sandbox · Celery background jobs with progress/retries/saved results.
**Should** — Bull/Bear/Risk debate & decision cards · context meter · human approval workflow · tamper-evident audit.
**Could** — LLM planner (done, optional) · live Nasdaq feed (done, fallback) · scheduled morning brief.
**Won’t (this release)** — real order routing, options, non-US markets, intraday streaming.

## Success metrics
| Metric | Target |
|---|---|
| Time from question → decision-ready view | < 15 s p50 (offline planner) |
| Analyses with provenance + assumptions shown | 100 % |
| Policy-denied actions that executed | 0 |
| Runs reconstructable from audit log | 100 % |
| Sandbox escapes in test suite | 0 |
| Raw tool tokens kept out of model context | > 90 % |

## Risks & mitigations
| Risk | Mitigation |
|---|---|
| Users mistake simulated data for real | Persistent SIMULATED badges, per-field provenance, explanation footer |
| Hallucinated numbers | Numbers come from code in the sandbox; LLM only plans and narrates |
| Unofficial Nasdaq endpoints change | Provider interface + circuit breaker + licensed-feed swap |
| Over-trust in “conviction” score | Rule-based, decomposed, with triggers that invalidate it; not advice |

## Release plan
**MVP** (this repo): screen / analyze / compare / what-if / overview / book / back-test, decision cards, approvals, audit. **v1.1**: licensed data feed, Cognito auth, Terraform, S3 audit archive. **v1.2**: scheduled briefs, alerts, multi-user books.
