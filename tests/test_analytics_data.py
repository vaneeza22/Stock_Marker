import numpy as np
import pandas as pd
import pytest

from meridian.analytics import fundamental as fa
from meridian.analytics import simulation as sim
from meridian.analytics import technical as ta
from meridian.data.providers import AutoProvider, NasdaqProvider, SyntheticProvider, history_df


@pytest.fixture(scope="module")
def prov():
    return SyntheticProvider()


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ta.rsi(up).dropna().iloc[-1] == 100
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ta.rsi(down).dropna().iloc[-1] < 1
    r = ta.rsi(pd.Series(np.random.RandomState(1).normal(0, 1, 200).cumsum() + 100)).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_bollinger_is_mean_plus_minus_two_sigma(prov):
    df = history_df(prov.history("MSFT", 300))
    lo, mid, up = ta.bollinger(df.close)
    win = df.close.iloc[-20:]
    assert abs(mid.iloc[-1] - win.mean()) < 1e-9
    assert abs(up.iloc[-1] - (win.mean() + 2 * win.std(ddof=0))) < 1e-9
    assert (up.dropna() >= lo.dropna()).all()


def test_snapshot_shape_and_scores(prov):
    s = ta.snapshot(history_df(prov.history("NVDA", 400)))
    for k in ("price", "rsi14", "trend", "tech_score", "regime", "levels", "patterns"):
        assert k in s
    assert 0 <= s["tech_score"] <= 100 and 0 <= s["rsi14"] <= 100


def test_patterns_engulfing():
    df = pd.DataFrame({"open": [10, 10.5, 9.4], "high": [10.6, 10.6, 11.2], "low": [9.9, 9.8, 9.3],
                       "close": [10.4, 9.9, 11.0], "volume": [1, 1, 1]})
    assert "bullish_engulfing" in ta.detect_patterns(df)


def test_synthetic_is_deterministic_and_labelled(prov):
    a, b = prov.history("AAPL", 100), SyntheticProvider().history("AAPL", 100)
    assert a["candles"] == b["candles"] and a["provenance"]["simulated"] is True
    c = a["candles"][-1]
    assert c["low"] <= min(c["open"], c["close"]) and c["high"] >= max(c["open"], c["close"])


def test_fundamentals_scoring(prov):
    f = fa.fund_snapshot(prov.fundamentals("CSCO"))
    assert 0 <= f["fund_score"] <= 100 and f["simulated_fields"]


def test_fund_score_handles_partial_nasdaq_data():
    f = fa.fund_snapshot({"ratios": {"pe": 30.0}, "fields_source": {"pe": "nasdaq"}, "sector": "x"})
    assert f["fund_score"] > 0 and f["simulated_fields"] == []


def test_monte_carlo_ordering_and_reproducible():
    r = np.random.RandomState(0).normal(0.0005, 0.01, 300)
    a, b = sim.monte_carlo(r, 100, 60, 500), sim.monte_carlo(r, 100, 60, 500)
    assert a == b
    for i in range(60):
        assert a["bands"]["p5"][i] <= a["bands"]["p50"][i] <= a["bands"]["p95"][i]


def test_portfolio_stats_weights_normalised(prov):
    px = pd.DataFrame({s: history_df(prov.history(s, 300)).close for s in ("AAPL", "MSFT")})
    st = sim.portfolio_stats({"AAPL": 2, "MSFT": 2}, px)
    assert abs(sum(st["weights"].values()) - 1) < 1e-6 and abs(sum(st["risk_contribution"].values()) - 1) < 0.01


def test_backtest_counts_costs(prov):
    df = history_df(prov.history("AMD", 700))
    r = sim.backtest_rsi(df, 35, 55)
    assert r["trades"] >= 1 and all(t["bars"] <= 20 for t in r["last_trades"])


# ---- providers ------------------------------------------------------------------------------
class FakeResp:
    def __init__(self, body, code=200): self.body, self.code = body, code
    def raise_for_status(self):
        if self.code >= 400: raise RuntimeError(f"http {self.code}")
    def json(self): return self.body


class FakeClient:
    def __init__(self, routes): self.routes, self.calls = routes, 0
    def get(self, url, params=None):
        self.calls += 1
        for k, v in self.routes.items():
            if k in url:
                if isinstance(v, Exception): raise v
                return FakeResp(v)
        return FakeResp({}, 404)


def _hist_body(n=60):
    rows = [{"date": f"{(i % 12) + 1:02d}/{(i % 27) + 1:02d}/2026", "close": f"${100 + i}.00", "volume": "1,000,000",
             "open": f"${99 + i}.00", "high": f"${101 + i}.00", "low": f"${98 + i}.00"} for i in range(n)]
    return {"data": {"tradesTable": {"rows": rows}}, "status": {"rCode": 200}}


def test_nasdaq_parsers():
    c = FakeClient({"/info": {"data": {"primaryData": {"lastSalePrice": "$232.14", "netChange": "+1.20", "percentageChange": "0.52%",
                                                       "lastTradeTimestamp": "Nov 10, 2026"}}, "status": {"rCode": 200}},
                    "/historical": _hist_body(),
                    "/summary": {"data": {"summaryData": {"PERatio": {"value": "35.1"}, "MarketCap": {"value": "3,500,000,000,000"}}},
                                 "status": {"rCode": 200}}})
    n = NasdaqProvider(client=c)
    q = n.quote("AAPL"); assert q["price"] == 232.14 and q["provenance"]["simulated"] is False
    h = n.history("AAPL", 40); assert len(h["candles"]) == 40 and h["candles"] == sorted(h["candles"], key=lambda x: x["date"])
    f = n.fundamentals("AAPL"); assert f["ratios"]["pe"] == 35.1 and f["ratios"]["market_cap"] == 3.5e12


def test_auto_falls_back_and_breaker_opens():
    nas = NasdaqProvider(client=FakeClient({"/info": ConnectionError("boom"), "/historical": ConnectionError("boom")}))
    auto = AutoProvider(nas, SyntheticProvider(), ttl_s=0, breaker_threshold=3, breaker_cooldown_s=60)
    for _ in range(3):
        q = auto.quote("AAPL")
        assert q["provenance"]["simulated"] is True and "fallback" in q["provenance"]["note"]
    assert auto.breaker_open
    calls = nas._client.calls
    auto.quote("MSFT")
    assert nas._client.calls == calls   # breaker open: Nasdaq is not hammered


def test_auto_prefers_nasdaq_and_marks_mixed_fundamentals():
    nas = NasdaqProvider(client=FakeClient({"/summary": {"data": {"summaryData": {"PERatio": {"value": "20.0"}}}, "status": {"rCode": 200}}}))
    f = AutoProvider(nas, SyntheticProvider()).fundamentals("AAPL")
    assert f["ratios"]["pe"] == 20.0 and f["fields_source"]["pe"] == "nasdaq" and f["fields_source"]["roe"] == "synthetic"
    assert f["provenance"]["mixed"] is True


def test_yahoo_provider_and_auto_chain_falls_through_nasdaq():
    import pandas as pd
    from meridian.data.providers import YahooProvider

    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    df = pd.DataFrame({"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": [100.0 + i for i in range(60)], "Volume": 1000}, index=idx)

    class FakeTicker:
        info = {"trailingPE": 25.0, "marketCap": 1e12, "debtToEquity": 150.0, "sector": "Technology"}
        def history(self, **kw): return df

    class FakeYF:
        Ticker = staticmethod(lambda s: FakeTicker())

    y = YahooProvider(yf=FakeYF())
    q = y.quote("AAPL")
    assert q["price"] == 159.0 and q["provenance"]["source"] == "yahoo" and not q["provenance"]["simulated"]
    assert len(y.history("AAPL", 40)["candles"]) == 40
    f = y.fundamentals("AAPL")
    assert f["ratios"]["debt_to_equity"] == 1.5 and f["fields_source"]["pe"] == "yahoo"
    nas = NasdaqProvider(client=FakeClient({"/info": ConnectionError("403"), "/historical": ConnectionError("403"), "/summary": ConnectionError("403")}))
    auto = AutoProvider([nas, y], SyntheticProvider(), ttl_s=0)
    assert auto.quote("AAPL")["provenance"]["source"] == "yahoo"
    mixed = auto.fundamentals("AAPL")
    assert mixed["fields_source"]["pe"] == "yahoo" and mixed["fields_source"]["roe"] == "synthetic"
