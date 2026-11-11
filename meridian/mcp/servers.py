"""The three MCP servers Meridian exposes to the harness.

 market     read-only market data + company fundamentals (Nasdaq-first, simulator fallback)
 analytics  indicator snapshots, back-tests, correlation (pure functions over market data)
 portfolio  paper-book context + `propose_trade`, which can ONLY create a pending approval
"""
from __future__ import annotations

import re

import pandas as pd

from ..analytics import fundamental as fa
from ..analytics import simulation as sim
from ..analytics import technical as ta
from ..config import Settings, get_settings
from ..data.providers import SECTOR, build_provider, history_df
from ..jobs.store import Store
from .protocol import McpServer

SYMBOL = {"type": "string", "description": "Nasdaq ticker, e.g. AAPL"}
SYM_RE = re.compile(r"^[A-Z]{1,5}$")


def _sym(s: str) -> str:
    s = s.upper().strip()
    if not SYM_RE.match(s):
        raise ValueError(f"invalid ticker '{s}'")
    return s


def market_server(provider, settings: Settings) -> McpServer:
    srv = McpServer("market")

    @srv.tool("universe", "List the tradable universe (Nasdaq technology names) with sectors.", {})
    def universe(_):
        return {"symbols": [{"symbol": s, "sector": SECTOR.get(s, "Technology")} for s in settings.universe]}

    @srv.tool("quote", "Latest price, change and volume for one ticker.", {"symbol": SYMBOL}, ["symbol"])
    def quote(a):
        return provider.quote(_sym(a["symbol"]))

    @srv.tool("history", "Daily OHLCV candles (oldest first) with provenance.",
              {"symbol": SYMBOL, "days": {"type": "integer", "minimum": 30, "maximum": 1000, "default": 180}}, ["symbol"])
    def history(a):
        return provider.history(_sym(a["symbol"]), a["days"])

    @srv.tool("fundamentals", "Valuation ratios and (simulated-if-unavailable) quarterly statements.",
              {"symbol": SYMBOL}, ["symbol"])
    def fundamentals(a):
        return provider.fundamentals(_sym(a["symbol"]))

    srv.add_resource("meridian://universe", "Universe", "Tradable universe", lambda: list(settings.universe))
    return srv


def analytics_server(provider, settings: Settings) -> McpServer:
    srv = McpServer("analytics")

    def df_for(symbol: str, days: int) -> pd.DataFrame:
        return history_df(provider.history(_sym(symbol), max(days, 260) if days < 260 else days))

    @srv.tool("snapshot", "Technical + fundamental snapshot for one ticker (trend, RSI, MACD, regime, levels, scores).",
              {"symbol": SYMBOL}, ["symbol"])
    def snapshot(a):
        sym = _sym(a["symbol"])
        h = provider.history(sym, 400)
        snap = ta.snapshot(history_df(h))
        f = provider.fundamentals(sym)
        return {"symbol": sym, "technical": snap, "fundamental": fa.fund_snapshot(f),
                "provenance": {"prices": h["provenance"], "fundamentals": f["provenance"]}}

    @srv.tool("indicators", "Aligned indicator series (SMA20/50/200, Bollinger, RSI14, MACD) for charting.",
              {"symbol": SYMBOL, "days": {"type": "integer", "minimum": 30, "maximum": 600, "default": 180}}, ["symbol"])
    def indicators(a):
        df = df_for(a["symbol"], 600)
        ind = ta.indicator_series(df)
        n = a["days"]
        return {"symbol": a["symbol"].upper(), **{k: v[-n:] for k, v in ind.items()}}

    @srv.tool("backtest_rsi", "Back-test a long-only RSI mean-reversion rule on one ticker.",
              {"symbol": SYMBOL, "entry": {"type": "number", "minimum": 5, "maximum": 50, "default": 30},
               "exit": {"type": "number", "minimum": 40, "maximum": 90, "default": 55},
               "days": {"type": "integer", "minimum": 120, "maximum": 1000, "default": 700}}, ["symbol"])
    def backtest(a):
        df = df_for(a["symbol"], a["days"])
        res = sim.backtest_rsi(df, a["entry"], a["exit"])
        res["symbol"] = a["symbol"].upper()
        return res

    @srv.tool("correlation", "Return correlation matrix for several tickers.",
              {"symbols": {"type": "array"}, "days": {"type": "integer", "minimum": 60, "maximum": 600, "default": 250}},
              ["symbols"])
    def correlation(a):
        syms = [_sym(s) for s in a["symbols"]][:12]
        px = pd.DataFrame({s: history_df(provider.history(s, a["days"])).set_index("date")["close"] for s in syms})
        c = px.pct_change().dropna().corr().round(2)
        return {"symbols": list(c.columns), "matrix": c.values.tolist()}

    return srv


def portfolio_server(store: Store, provider, settings: Settings) -> McpServer:
    srv = McpServer("portfolio")

    @srv.tool("holdings", "Current paper-trading book with marked-to-market values.", {})
    def holdings(_):
        rows, total = [], 0.0
        for h in store.holdings():
            px = provider.quote(h["symbol"])["price"]
            mv = px * h["qty"]
            total += mv
            rows.append({**h, "price": px, "market_value": round(mv, 2),
                         "pnl_pct": round((px / h["avg_cost"] - 1) * 100, 2)})
        for r in rows:
            r["weight"] = round(r["market_value"] / total, 4) if total else 0
        return {"mode": "PAPER", "total_value": round(total, 2), "positions": rows}

    @srv.tool("propose_trade",
              "Create a PENDING paper-trade approval request. Never executes: a human must approve it in the UI.",
              {"symbol": SYMBOL, "side": {"type": "string", "enum": ["buy", "sell"]},
               "qty": {"type": "number", "minimum": 1, "maximum": 100000},
               "rationale": {"type": "string"}, "run_id": {"type": "string", "default": "adhoc"}},
              ["symbol", "side", "qty", "rationale"], read_only=False, sensitivity="high")
    def propose_trade(a):
        sym = _sym(a["symbol"])
        px = provider.quote(sym)["price"]
        aid = store.create_approval(a["run_id"], sym, a["side"], a["qty"], px, a["rationale"][:500], "agent")
        return {"approval_id": aid, "status": "pending", "reference_price": px,
                "note": "Not executed. Requires explicit human approval."}

    srv.add_resource("meridian://portfolio/holdings", "Holdings", "Paper book", lambda: store.holdings())
    return srv


def build_server(name: str, settings: Settings | None = None) -> McpServer:
    settings = settings or get_settings()
    provider = build_provider(settings)
    if name == "market":
        return market_server(provider, settings)
    if name == "analytics":
        return analytics_server(provider, settings)
    if name == "portfolio":
        return portfolio_server(Store(settings.db_path), provider, settings)
    raise KeyError(name)


SERVER_NAMES = ("market", "analytics", "portfolio")
