"""FastAPI surface: runs (async via Celery/threads), direct chart reads, approvals, audit, MCP-over-HTTP, and the dashboard."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..analytics import fundamental as fa
from ..analytics import technical as ta
from ..data.providers import history_df
from ..harness.policy import ROLES
from ..jobs import runner
from ..mcp.servers import build_server
from ..services import get_services

WEB = Path(__file__).resolve().parents[2] / "web"


class RunIn(BaseModel):
    prompt: str = Field(..., max_length=4000)
    session_id: Optional[str] = None


class ApprovalIn(BaseModel):
    symbol: str
    side: str = "buy"
    qty: float = Field(..., gt=0, le=100000)
    rationale: str = ""
    run_id: str = "ui"


class DecisionIn(BaseModel):
    decision: str


def role_of(x_role: Optional[str]) -> str:
    r = (x_role or "analyst").lower()
    if r not in ROLES:
        raise HTTPException(400, f"unknown role '{r}'")
    return r


def create_app() -> FastAPI:
    app = FastAPI(title="Meridian - Agentic Portfolio Desk", version="1.0.0")
    mcp_http: Dict[str, Any] = {}

    @app.get("/api/health")
    def health():
        svc = get_services()
        p = svc.provider
        return {"status": "ok", "provider": getattr(p, "name", "?"), "breaker_open": getattr(p, "breaker_open", False),
                "provider_last_error": getattr(p, "last_error", None), "sandbox": svc.settings.sandbox_backend,
                "jobs": svc.settings.job_backend, "llm": svc.llm.available, "model": svc.settings.model if svc.llm.available else None,
                "mcp_transport": svc.settings.mcp_transport, "tools": len(svc.registry.tools)}

    @app.get("/api/tools")
    def tools():
        return get_services().registry.catalog()

    # ---- direct, read-only chart path (no agent involved; still uses the same provider + analytics) -----
    @app.get("/api/overview")
    def overview():
        svc = get_services()
        rows = []
        for sym in svc.settings.universe:
            h = svc.provider.history(sym, 400)
            df = history_df(h)
            s = ta.snapshot(df)
            rows.append({"symbol": sym, "price": s["price"], "change_pct": round((s["ret_1d"] or 0) * 100, 2), "rsi": s["rsi14"],
                         "trend": s["trend"], "tech_score": s["tech_score"], "regime": s["regime"]["label"],
                         "spark": df["close"].tail(40).round(2).tolist(), "simulated": h["provenance"]["simulated"]})
        return {"rows": rows, "provenance": h["provenance"]}

    @app.get("/api/symbol/{symbol}")
    def symbol(symbol: str, days: int = Query(160, ge=40, le=600)):
        svc = get_services()
        sym = symbol.upper()
        if sym not in svc.settings.universe:
            raise HTTPException(404, "symbol not in universe")
        h = svc.provider.history(sym, 600)
        df = history_df(h)
        ind = ta.indicator_series(df)
        f = svc.provider.fundamentals(sym)
        return {"symbol": sym, "candles": h["candles"][-days:], "indicators": {k: v[-days:] for k, v in ind.items()},
                "snapshot": ta.snapshot(df), "fundamental": fa.fund_snapshot(f),
                "quote": svc.provider.quote(sym), "provenance": {"prices": h["provenance"], "fundamentals": f["provenance"]}}

    # ---- agent runs -------------------------------------------------------------------------
    @app.post("/api/runs", status_code=202)
    def create_run(body: RunIn, x_role: Optional[str] = Header(None), x_user: Optional[str] = Header("demo")):
        svc = get_services()
        rid = svc.store.create_run(body.prompt, x_user or "demo", role_of(x_role), body.session_id)
        backend = runner.submit(rid)
        run = svc.store.get_run(rid, with_events=False)
        return {"run_id": rid, "session_id": run["session_id"], "backend": backend}

    @app.get("/api/runs")
    def list_runs(limit: int = 15):
        return get_services().store.list_runs(limit)

    @app.get("/api/runs/{rid}")
    def get_run(rid: str, after: int = 0):
        run = get_services().store.get_run(rid)
        if not run:
            raise HTTPException(404, "run not found")
        run["events"] = [e for e in run["events"] if e["seq"] > after]
        return run

    @app.get("/api/runs/{rid}/stream")
    async def stream(rid: str):
        svc = get_services()

        async def gen():
            last = 0
            while True:
                run = svc.store.get_run(rid, with_events=False)
                if run is None:
                    yield "event: error\ndata: {}\n\n"
                    return
                for e in svc.store.events(rid, last):
                    last = e["seq"]
                    yield f"event: step\ndata: {json.dumps({**e, 'progress': run['progress']})}\n\n"
                if run["status"] in ("completed", "failed", "denied"):
                    yield f"event: done\ndata: {json.dumps({'status': run['status']})}\n\n"
                    return
                await asyncio.sleep(0.25)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/sessions/{sid}/context")
    def session_context(sid: str):
        from ..harness.context import ContextManager
        d = get_services().store.load_session(sid)
        if not d:
            raise HTTPException(404, "no such session")
        cm = ContextManager.from_dict(d)
        return {"stats": cm.stats(), "items": [{"kind": i.kind, "tokens": i.tokens, "pinned": i.pinned, "ref": i.ref,
                                                 "preview": i.text[:160]} for i in cm.items]}

    # ---- audit ------------------------------------------------------------------------------
    @app.get("/api/audit/verify")
    def audit_verify():
        ok, bad, n = get_services().audit.verify()
        return {"ok": ok, "first_bad_seq": bad, "records": n}

    @app.get("/api/audit/{rid}")
    def audit_run(rid: str):
        return get_services().audit.events(rid)

    # ---- portfolio + human approvals ----------------------------------------------------------
    @app.get("/api/portfolio")
    def portfolio():
        svc = get_services()
        return svc.registry.call("portfolio.holdings", {})

    @app.get("/api/approvals")
    def approvals(status: Optional[str] = None):
        return get_services().store.list_approvals(status)

    @app.post("/api/approvals", status_code=201)
    def request_approval(body: ApprovalIn, x_role: Optional[str] = Header(None), x_user: Optional[str] = Header("demo")):
        role = role_of(x_role)
        if not ROLES[role]["propose"]:
            raise HTTPException(403, f"role '{role}' may not request trades")
        svc = get_services()
        if body.side not in ("buy", "sell"):
            raise HTTPException(400, "side must be buy|sell")
        px = svc.provider.quote(body.symbol.upper())["price"]
        aid = svc.store.create_approval(body.run_id, body.symbol.upper(), body.side, body.qty, px, body.rationale[:500], x_user or "demo")
        svc.audit.append(body.run_id, "approval.requested", {"approval": aid, "symbol": body.symbol, "side": body.side, "qty": body.qty}, actor=x_user or "demo")
        return svc.store.get_approval(aid)

    @app.post("/api/approvals/{aid}/decide")
    def decide(aid: str, body: DecisionIn, x_role: Optional[str] = Header(None), x_user: Optional[str] = Header("demo")):
        if role_of(x_role) != "pm":
            raise HTTPException(403, "only a PM can decide approvals")
        svc = get_services()
        try:
            a = svc.store.decide_approval(aid, body.decision, x_user or "demo")
        except KeyError:
            raise HTTPException(404, "approval not found")
        except ValueError as e:
            raise HTTPException(409, str(e))
        svc.audit.append(a["run_id"], f"approval.{a['status']}", {"approval": aid, "by": x_user, "execution": a.get("execution_json")}, actor=x_user or "demo")
        return a

    # ---- MCP over HTTP (so external clients - e.g. Claude Desktop via a proxy - can use the same servers) ----
    @app.post("/mcp/{name}")
    async def mcp(name: str, request: Request):
        if name not in ("market", "analytics", "portfolio"):
            raise HTTPException(404, "unknown MCP server")
        srv = mcp_http.setdefault(name, build_server(name))
        resp = srv.handle(await request.json())
        return JSONResponse(resp) if resp is not None else JSONResponse(None, status_code=202)

    if WEB.exists():
        @app.get("/")
        def index():
            return FileResponse(WEB / "index.html")
        app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
