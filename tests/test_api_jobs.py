import time

import pytest
from fastapi.testclient import TestClient

from meridian.harness.core import TransientError
from meridian.jobs import runner


@pytest.fixture()
def client(env):
    from meridian.api.app import create_app
    return TestClient(create_app())


def wait(client, rid, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        r = client.get(f"/api/runs/{rid}").json()
        if r["status"] in ("completed", "failed", "denied"):
            return r
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_health_and_direct_reads(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["tools"] == 10 and h["llm"] is False
    assert len(client.get("/api/overview").json()["rows"]) == 16
    s = client.get("/api/symbol/AAPL?days=100").json()
    assert len(s["candles"]) == 100 and len(s["indicators"]["rsi14"]) == 100 and s["provenance"]["prices"]["simulated"]
    assert client.get("/api/symbol/ZZZZ").status_code == 404
    assert client.get("/").status_code == 200


def test_async_run_with_progress_events_and_session_context(client):
    r = client.post("/api/runs", json={"prompt": "Analyze NVDA"}, headers={"x-role": "analyst"})
    assert r.status_code == 202
    run = wait(client, r.json()["run_id"])
    assert run["status"] == "completed" and run["progress"] == 1.0
    types = [e["type"] for e in run["events"]]
    assert types.index("plan.created") < types.index("sandbox.start") < types.index("run.completed")
    r2 = client.post("/api/runs", json={"prompt": "Analyze AMD", "session_id": r.json()["session_id"]}, headers={"x-role": "analyst"})
    wait(client, r2.json()["run_id"])
    ctx = client.get(f"/api/sessions/{r.json()['session_id']}/context").json()
    assert sum(1 for i in ctx["items"] if i["kind"] == "user") == 2      # context persisted across runs/workers


def test_sse_stream_ends_with_done(client):
    rid = client.post("/api/runs", json={"prompt": "market regime"}).json()["run_id"]
    with client.stream("GET", f"/api/runs/{rid}/stream") as s:
        body = "".join(s.iter_text())
    assert "event: step" in body and "event: done" in body


def test_bad_role_and_oversized_prompt(client):
    assert client.post("/api/runs", json={"prompt": "x"}, headers={"x-role": "root"}).status_code == 400
    assert client.post("/api/runs", json={"prompt": "x" * 5000}).status_code == 422


def test_human_approval_workflow(client):
    body = {"symbol": "AAPL", "side": "buy", "qty": 5, "rationale": "test"}
    assert client.post("/api/approvals", json=body, headers={"x-role": "viewer"}).status_code == 403
    a = client.post("/api/approvals", json=body, headers={"x-role": "pm"}).json()
    assert a["status"] == "pending"
    assert client.post(f"/api/approvals/{a['id']}/decide", json={"decision": "approved"}, headers={"x-role": "analyst"}).status_code == 403
    before = {p["symbol"]: p["qty"] for p in client.get("/api/portfolio").json()["positions"]}
    d = client.post(f"/api/approvals/{a['id']}/decide", json={"decision": "approved"}, headers={"x-role": "pm"})
    assert d.status_code == 200 and '"PAPER"' in d.json()["execution_json"]
    after = {p["symbol"]: p["qty"] for p in client.get("/api/portfolio").json()["positions"]}
    assert after["AAPL"] == before["AAPL"] + 5
    assert client.post(f"/api/approvals/{a['id']}/decide", json={"decision": "rejected"}, headers={"x-role": "pm"}).status_code == 409
    assert client.get("/api/audit/verify").json()["ok"]


def test_paper_book_cannot_go_short(client):
    a = client.post("/api/approvals", json={"symbol": "NVDA", "side": "sell", "qty": 9999, "rationale": "x"}, headers={"x-role": "pm"}).json()
    assert client.post(f"/api/approvals/{a['id']}/decide", json={"decision": "approved"}, headers={"x-role": "pm"}).status_code == 409


def test_mcp_over_http(client):
    r = client.post("/mcp/analytics", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    assert {t["name"] for t in r["result"]["tools"]} >= {"snapshot", "backtest_rsi"}
    call = client.post("/mcp/market", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                            "params": {"name": "quote", "arguments": {"symbol": "AAPL"}}}).json()
    assert call["result"]["structuredContent"]["price"] > 0
    assert client.post("/mcp/nope", json={}).status_code == 404


# ---- Celery / job layer ----------------------------------------------------------------------------
def test_celery_task_eager_executes_and_is_idempotent(env):
    from meridian.jobs.tasks import app as celery_app, run_analysis
    from meridian.services import get_services
    celery_app.conf.task_always_eager = True
    st = get_services().store
    rid = st.create_run("Analyze CSCO", "demo", "analyst")
    run_analysis.delay(rid).get()
    first = st.get_run(rid)
    assert first["status"] == "completed" and first["result"]["intent"] == "analyze"
    n_events = len(first["events"])
    run_analysis.delay(rid).get()                      # at-least-once redelivery must not re-run
    assert len(st.get_run(rid)["events"]) == n_events


def test_celery_retries_transient_failures(env):
    """autoretry_for=(TransientError,) must put the task in RETRY (not FAILURE) and keep the run recoverable."""
    from meridian.jobs.tasks import app as celery_app, run_analysis
    from meridian.services import get_services
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    svc = get_services()
    calls = {"n": 0}
    real = svc.harness.run

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("provider 503")
        return real(*a, **k)
    svc.harness.run = flaky
    rid = svc.store.create_run("Analyze CSCO", "demo", "analyst")
    res = run_analysis.apply(args=[rid])        # eager mode re-applies the retry signature itself, as a worker would
    assert res.state == "SUCCESS" and calls["n"] == 3, (res.state, calls)
    run = svc.store.get_run(rid)
    assert run["status"] == "completed" and [e["type"] for e in run["events"]].count("job.retry") == 2


def test_thread_backend_gives_up_after_retries(env, monkeypatch):
    from meridian.services import get_services
    svc = get_services()
    monkeypatch.setattr(svc.harness, "run", lambda *a, **k: (_ for _ in ()).throw(TransientError("down")))
    rid = svc.store.create_run("Analyze CSCO", "demo", "analyst")
    runner.execute_with_retries(rid, max_retries=2, base_delay=0)
    r = svc.store.get_run(rid)
    assert r["status"] == "failed" and "transient" in r["error"] and r["attempt"] >= 2
