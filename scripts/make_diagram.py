"""Generates docs/architecture.svg (AWS-style). Run: python scripts/make_diagram.py"""
from pathlib import Path

W, H = 1900, 1230
out = []
add = out.append

COL = {"compute": "#ED7100", "storage": "#7AA116", "db": "#C925D1", "net": "#8C4FFF", "sec": "#DD344C",
       "mgmt": "#E7157B", "ext": "#5D6C8A", "app": "#3b82f6", "ai": "#0ea5a4", "client": "#334155"}


def box(x, y, w, h, label, stroke, dash=None, fill="none", lab_color=None, sub=None, rx=10, right=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"{d}/>')
    tx, anc = (x + w - 12, "end") if right else (x + 12, "start")
    add(f'<text x="{tx}" y="{y + 20}" class="boxlab" fill="{lab_color or stroke}" text-anchor="{anc}">{label}</text>')
    if sub:
        add(f'<text x="{tx}" y="{y + 36}" class="boxsub" text-anchor="{anc}">{sub}</text>')


def icon(cx, cy, label, kind, glyph, sub=None, s=62):
    c = COL[kind]
    x, y = cx - s / 2, cy - s / 2
    add(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="9" fill="{c}"/>')
    add(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="9" fill="url(#shine)"/>')
    add(f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" class="glyph">{glyph}</text>')
    add(f'<text x="{cx}" y="{y + s + 16}" text-anchor="middle" class="ilab">{label}</text>')
    if sub:
        for i, line in enumerate(sub.split("|")):
            add(f'<text x="{cx}" y="{y + s + 30 + i * 12}" text-anchor="middle" class="isub">{line}</text>')


def arrow(pts, n=None, color="#1e293b", dash=None, label=None, lx=None, ly=None, both=False):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    ms = ' marker-start="url(#ah)"' if both else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{da} marker-end="url(#ah)"{ms}/>')
    if n is not None:
        mx, my = (lx, ly) if lx is not None else pts[len(pts) // 2 - 1 if len(pts) > 2 else 0]
        if lx is None:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        add(f'<circle cx="{mx}" cy="{my}" r="12" fill="#0f172a"/><text x="{mx}" y="{my + 4}" text-anchor="middle" class="num">{n}</text>')
    if label:
        add(f'<text x="{lx + 16 if lx is not None else pts[0][0]}" y="{(ly if ly is not None else pts[0][1]) + 4}" class="alab">{label}</text>')


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif">')
add('''<defs>
<linearGradient id="shine" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset="1" stop-color="#000" stop-opacity=".12"/></linearGradient>
<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1e293b"/></marker>
<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1" fill="#e2e8f0"/></pattern>
</defs>
<style>
.boxlab{font-size:14px;font-weight:700;letter-spacing:.2px}.boxsub{font-size:11px;fill:#64748b}
.ilab{font-size:12.5px;font-weight:650;fill:#0f172a}.isub{font-size:10.5px;fill:#475569}
.glyph{font-size:22px;font-weight:700;fill:#fff;letter-spacing:.5px}.num{font-size:12px;font-weight:700;fill:#fff}
.alab{font-size:11px;fill:#334155;font-style:italic}.title{font-size:28px;font-weight:800;fill:#0f172a}.tsub{font-size:14px;fill:#475569}
.leg{font-size:12px;fill:#0f172a}.legh{font-size:13px;font-weight:700;fill:#0f172a}.tiny{font-size:11px;fill:#475569}
</style>''')
add(f'<rect width="{W}" height="{H}" fill="#f8fafc"/><rect width="{W}" height="{H}" fill="url(#dots)"/>')
add('<text x="36" y="52" class="title">Meridian — Agentic Portfolio Desk on AWS</text>')
add('<text x="36" y="76" class="tsub">Cloud harness · MCP · programmatic tool calling · isolated Python sandbox · Celery workers · human-in-the-loop approvals</text>')

# ── left: clients & CI ─────────────────────────────────────────────────────────
icon(100, 330, "Portfolio Manager", "client", "PM", "Browser · dashboard|SSE progress")
icon(100, 1000, "GitHub", "client", "GH", "Actions: ruff · pytest|Celery integ. · docker build")
# ── edge ───────────────────────────────────────────────────────────────────────
box(200, 110, 190, 590, "Edge", "#8C4FFF", dash="6 4", sub="global")
icon(295, 190, "WAF", "sec", "WAF", "rate / bot rules")
icon(295, 330, "CloudFront", "net", "CF", "HTTPS · caching")
icon(295, 480, "S3 — static UI", "storage", "S3", "dashboard (SVG engine)")
icon(295, 620, "Cognito", "sec", "ID", "JWT → viewer/analyst/pm")

# ── AWS region / VPC ────────────────────────────────────────────────────────────
box(420, 100, 1130, 1090, "AWS Region  ·  VPC 10.0.0.0/16", "#334155", sub="3 AZs; tiers shown once")
box(440, 150, 200, 1000, "Public subnets", "#7AA116", dash="6 4")
icon(540, 330, "ALB", "net", "ALB", "TLS · /api · /mcp")
icon(540, 900, "NAT Gateway", "net", "NAT", "egress allow-list")

box(660, 150, 600, 330, "Private subnets — API and queue", "#3b82f6", dash="6 4")
icon(770, 280, "FastAPI service", "compute", "API", "ECS Fargate · SSE|runs · approvals · audit")
icon(960, 280, "ElastiCache Redis", "db", "RD", "Celery broker · cache|task queue")
icon(1150, 280, "Celery Beat", "mgmt", "BT", "EventBridge sched.|cache warm-up · briefs")

box(660, 510, 600, 380, "Private subnets — ECS (EC2) Celery workers", "#ED7100", dash="6 4", sub="autoscale on queue depth · acks_late · retries w/ backoff", right=True)
box(680, 560, 270, 310, "Harness", "#ED7100", fill="#fff7ed", sub="orchestration")
for i, t in enumerate(["request + tool policy (roles, scope, budget)", "context manager (budget · offload · summarise)",
                       "planner → PTC program (LLM | template)", "self-debug loop · quarantine", "Bull/Bear/Risk debate → decision card",
                       "hash-chained audit"]):
    add(f'<text x="694" y="{622 + i * 38}" class="tiny">• {t}</text>')
box(970, 560, 270, 310, "MCP layer", "#0ea5a4", fill="#f0fdfa", sub="JSON-RPC 2.0 · tools/resources")
for i, (n, d) in enumerate([("market", "quote · history · fundamentals"), ("analytics", "snapshot · indicators · backtest"),
                            ("portfolio", "holdings · propose_trade (HITL)")]):
    add(f'<rect x="984" y="{598 + i * 84}" width="242" height="68" rx="8" fill="#ccfbf1" stroke="#0ea5a4"/>'
        f'<text x="998" y="{622 + i * 84}" class="boxlab" fill="#0f766e">MCP server: {n}</text><text x="998" y="{640 + i * 84}" class="tiny">{d}</text>')

box(1290, 510, 240, 380, "Isolated sandbox subnet", "#DD344C", dash="6 4", sub="no route to internet / NAT", right=True)
icon(1410, 620, "Sandbox container", "sec", "BOX", "--network none · read-only|cap-drop ALL · 64 pids|CPU/mem/wall limits", s=70)
add('<text x="1310" y="760" class="tiny">Runs generated Python (PTC):</text><text x="1310" y="776" class="tiny">tools.market_history(...)</text><text x="1310" y="792" class="tiny">tools.map(\'analytics_snapshot\', …)</text>'
    '<text x="1310" y="808" class="tiny">→ charts · tables · signals</text><text x="1310" y="832" class="tiny">tool calls leave only via the</text><text x="1310" y="848" class="tiny">policy-checked stdio bridge</text>')

box(660, 920, 880, 240, "Private subnets — data and secrets", "#C925D1", dash="6 4", right=True)
icon(760, 1030, "RDS PostgreSQL", "db", "DB", "runs · events · sessions|approvals · paper book")
icon(930, 1030, "S3 — results", "storage", "S3", "artifacts · decision cards")
icon(1100, 1030, "S3 — audit (Object Lock)", "storage", "S3", "hash-chained JSONL archive")
icon(1270, 1030, "Secrets Manager", "sec", "SM", "API keys (never in sandbox)")
icon(1440, 1030, "KMS", "sec", "KMS", "encryption · checkpoint signing")

# ── right: external ─────────────────────────────────────────────────────────────
box(1580, 110, 290, 1080, "External and observability", "#5D6C8A", dash="6 4")
icon(1725, 220, "Nasdaq data", "ext", "NQ", "api.nasdaq.com (live)|licensed feed in prod")
icon(1725, 410, "Anthropic API", "ai", "AI", "LLM planner / narrator|optional; offline planner else")
icon(1725, 620, "CloudWatch + X-Ray", "mgmt", "CW", "logs · metrics · traces|queue-depth and error alarms")
icon(1725, 800, "SNS / Alarms", "mgmt", "SNS", "pager · Slack")
icon(1725, 990, "ECR", "compute", "ECR", "app + sandbox images")

# ── flows ───────────────────────────────────────────────────────────────────────
EG = "#c2410c"
arrow([(131, 330), (264, 330)], 1, lx=200, ly=330)                                        # browser → CloudFront
arrow([(326, 340), (356, 340), (356, 480), (326, 480)], None)                             # CF → S3 (static UI)
arrow([(326, 322), (509, 322)], 2, lx=440, ly=322)                                        # CF → ALB (/api)
arrow([(326, 620), (470, 620), (470, 350), (509, 350)], None, dash="5 4")                 # Cognito JWT → ALB
add('<text x="338" y="612" class="alab">JWT validated at ALB</text>')
arrow([(571, 330), (620, 330), (620, 262), (739, 262)], 3, lx=680, ly=262)                # ALB → API
arrow([(801, 280), (929, 280)], 4, lx=865, ly=280)                                        # API → Redis enqueue
arrow([(1119, 280), (991, 280)], None, dash="5 4")                                        # Beat → Redis
arrow([(960, 366), (960, 436), (820, 436), (820, 558)], 5, lx=960, ly=436)                # Redis → worker (harness)
arrow([(950, 690), (970, 690)], 6, lx=960, ly=676)                                        # harness → MCP
arrow([(1240, 650), (1290, 650)], 7, lx=1265, ly=636, both=True)                          # PTC bridge <-> sandbox
# egress trunk: workers -> NAT -> external (Nasdaq, Anthropic)
arrow([(1100, 872), (1100, 908), (571, 908)], None, color=EG, dash="6 4")
add(f'<text x="600" y="903" class="alab" fill="{EG}" style="fill:{EG}">egress: market data + LLM calls (allow-listed)</text>')
arrow([(509, 900), (470, 900), (470, 1175), (1604, 1175), (1604, 220), (1694, 220)], 8, color=EG, dash="6 4", lx=1604, ly=700)
arrow([(1604, 410), (1694, 410)], 9, color=EG, dash="6 4", lx=1650, ly=410)
# persistence
arrow([(760, 872), (760, 999)], 10, lx=760, ly=968)                                       # workers → RDS
arrow([(850, 872), (850, 945), (930, 945), (930, 999)], None)                             # workers → S3 results
arrow([(1010, 872), (1010, 955), (1100, 955), (1100, 999)], None)                         # audit → S3 audit
arrow([(729, 1015), (652, 1015), (652, 298), (739, 298)], 11, dash="5 4", lx=652, ly=640) # API polls RDS (progress / SSE)
arrow([(1694, 620), (1556, 620)], None, dash="3 3")                                       # CloudWatch <- logs
arrow([(131, 1000), (185, 1000), (185, 1212), (1725, 1212), (1725, 1074)], 12, dash="4 4", lx=700, ly=1212)  # CI/CD → ECR

# ── legend ─────────────────────────────────────────────────────────────────────
lx, ly = 22, 760
steps = ["1  HTTPS + SSE to the UI", "2  /api → ALB (WAF in front)", "3  JWT → role, route to API", "4  enqueue run (Celery)",
         "5  worker consumes, ack late", "6  harness → MCP (JSON-RPC)", "7  PTC program ⇄ sandbox bridge", "8  egress: Nasdaq data",
         "9  egress: LLM planner", "10 persist state + audit", "11 API polls / streams progress", "12 CI/CD → ECR → ECS"]
add(f'<rect x="{lx - 8}" y="{ly - 26}" width="178" height="{len(steps) * 14 + 38}" rx="10" fill="#fff" stroke="#cbd5e1"/>')
add(f'<text x="{lx}" y="{ly - 6}" class="legh">Numbered data flow</text>')
for i, t in enumerate(steps):
    add(f'<text x="{lx}" y="{ly + 14 + i * 14}" class="leg" style="font-size:10.5px">{t}</text>')
add('</svg>')
Path(__file__).resolve().parents[1].joinpath("docs/architecture.svg").write_text("\n".join(out))
print("ok")
