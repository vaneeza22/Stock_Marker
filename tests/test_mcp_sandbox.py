import dataclasses

import pytest

from meridian.mcp.client import ToolError, build_registry
from meridian.sandbox.executor import Sandbox
from meridian.sandbox.validator import validate


# ---- MCP --------------------------------------------------------------------------------------
def test_protocol_methods(svc):
    srv = svc.registry.clients["market"].t.server
    assert srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]["serverInfo"]["name"] == "market"
    assert srv.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"] == -32601
    assert srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "history", "arguments": {}}})["error"]["code"] == -32602
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    res = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "meridian://universe"}})
    assert "AAPL" in res["result"]["contents"][0]["text"]


def test_registry_discovers_tools_and_annotations(svc):
    t = svc.registry.tools
    assert {"market.history", "analytics.snapshot", "portfolio.propose_trade"} <= set(t)
    assert t["portfolio.propose_trade"].sensitivity == "high" and not t["portfolio.propose_trade"].read_only
    assert t["market.quote"].read_only


def test_argument_validation(svc):
    for bad in ({"symbol": "aapl!"}, {"symbol": "AAPL", "days": 5}, {"symbol": "AAPL", "days": "x"}, {"symbol": "AAPL", "x": 1}):
        with pytest.raises(ToolError):
            svc.registry.call("market.history", bad)


def test_propose_trade_never_executes(svc):
    before = {h["symbol"]: h["qty"] for h in svc.store.holdings()}
    r = svc.registry.call("portfolio.propose_trade", {"symbol": "MSFT", "side": "buy", "qty": 50, "rationale": "t"})
    assert r["status"] == "pending"
    assert {h["symbol"]: h["qty"] for h in svc.store.holdings()} == before


def test_stdio_transport_roundtrip(env):
    from meridian.config import get_settings
    reg = build_registry(dataclasses.replace(get_settings(), mcp_transport="stdio"))
    try:
        assert reg.call("analytics.snapshot", {"symbol": "AAPL"})["technical"]["price"] > 0
    finally:
        reg.close()


# ---- sandbox ------------------------------------------------------------------------------------
def echo(tool, args):
    return {"tool": tool, "args": args}


@pytest.fixture(scope="module")
def sb():
    return Sandbox(timeout_s=6, mem_mb=1536)


def run(sb, code, validate_first=False):
    if validate_first:
        assert not validate(code)
    return sb.run(code, ["market_history", "x"], echo)


def test_sandbox_success_bridge_and_emit(sb):
    r = run(sb, "import numpy as np\nprint(np.arange(4).sum())\nx = tools.market_history(symbol='A')\nresult(x)\n"
                "table('t', ['a'], [[float('nan')]])", True)
    assert r.ok and r.stdout.strip() == "6" and [e["kind"] for e in r.emits] == ["result", "table"]
    assert r.emits[1]["data"]["rows"] == [[None]]       # NaN is sanitised to valid JSON


def test_sandbox_parallel_map(sb):
    r = run(sb, "result(tools.map('market_history', [{'symbol': 'A'}, {'symbol': 'B'}]))")
    assert r.ok and len(r.emits[0]["data"]) == 2 and r.tool_calls == 2


def test_sandbox_error_reports_user_frame(sb):
    r = run(sb, "x = [1]\nx[3]")
    assert not r.ok and r.error["type"] == "IndexError" and "line 2" in r.error_text()


def test_sandbox_wall_clock_timeout():
    r = Sandbox(timeout_s=2).run("while True: pass", [], echo)
    assert not r.ok and r.killed and "timeout" in r.killed.lower()


def test_sandbox_memory_limit(sb):
    r = run(sb, "x = [0] * 10**9")
    assert not r.ok and r.error["type"] in ("MemoryError", "SandboxCrash")


def test_unknown_tool_is_attribute_error(sb):
    r = run(sb, "tools.nope()")
    assert not r.ok and r.error["type"] == "AttributeError"


@pytest.mark.parametrize("code", [
    "import os", "import subprocess", "from os import path", "open('/etc/passwd')", "eval('1')", "exec('1')",
    "().__class__", "x = '__import__'", "getattr(tools, 'x')", "pd.read_csv('/etc/passwd')", "pd.DataFrame().to_csv('x')",
    "import socket", "global x",
])
def test_validator_blocks(code):
    assert validate(code), code


@pytest.mark.parametrize("code,exc", [
    ("open('/etc/passwd')", "NameError"),          # builtins stripped even if the validator were bypassed
    ("import os", "ImportError"),
    ("__import__('os')", "ImportError"),
    ("import socket", "ImportError"),
])
def test_runtime_defence_in_depth_without_validator(sb, code, exc):
    r = run(sb, code)                              # deliberately NOT validated
    assert not r.ok and r.error["type"] == exc


def test_sandbox_cannot_write_files(sb):
    r = run(sb, "np.save('/tmp/should_not_exist.npy', np.arange(3))")    # blocked by validator in prod; here by RLIMIT/blocked names
    assert not r.ok
