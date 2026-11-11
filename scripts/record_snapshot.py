"""Record API responses from a running Meridian server into a static snapshot for the offline demo page."""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011"
H = {"Content-Type": "application/json", "X-Role": "pm", "X-User": "demo-pm"}


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def stream(path):
    req = urllib.request.Request(BASE + path, headers=H)
    ev, out = None, []
    for raw in urllib.request.urlopen(req, timeout=120):
        line = raw.decode().rstrip("\n")
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:") and ev == "step":
            out.append(json.loads(line[5:]))
        elif ev == "done" and line == "":
            break
        if ev == "done":
            break
    return out


snap = {"health": call("/api/health"), "overview": call("/api/overview"), "portfolio": call("/api/portfolio"), "symbols": {}, "runs": {}}
for row in snap["overview"].get("rows", snap["overview"].get("watchlist", [])):
    s = row["symbol"]
    snap["symbols"][s] = call(f"/api/symbol/{s}?days=160")
syms = list(snap["symbols"])
prompts = ["Screen Nasdaq tech for RSI below 40 and size a $250k allocation", "Compare AAPL vs MSFT vs GOOGL", "What if I put 40% NVDA, 30% MSFT, 30% AAPL?",
           "How healthy is the market regime today?", "Review my portfolio", "Backtest RSI 25 on AMD", "Propose to buy 10 shares of MSFT"] + [f"Analyze {s}" for s in syms]
sid = None
for p in prompts:
    r = call("/api/runs", {"prompt": p, "session_id": sid})
    sid = r["session_id"]
    steps = stream(f"/api/runs/{r['run_id']}/stream")
    for _ in range(60):
        run = call(f"/api/runs/{r['run_id']}")
        if run["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    snap["runs"][p] = {"run": run, "steps": steps, "audit": call(f"/api/audit/{r['run_id']}")}
    print(run["status"], p, len(steps))
snap["audit_verify"] = call("/api/audit/verify")
json.dump(snap, open(sys.argv[2] if len(sys.argv) > 2 else "/tmp/snapshot.json", "w"), separators=(",", ":"))
