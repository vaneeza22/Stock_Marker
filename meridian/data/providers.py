"""Market-data providers.

* NasdaqProvider   - Nasdaq's public quote endpoints (api.nasdaq.com). Unofficial, so every
                     parser is defensive and failures raise ProviderError.
* SyntheticProvider- deterministic, seeded simulator. Always labelled `simulated: true` so no
                     number from it can be mistaken for market data.
* AutoProvider     - Nasdaq first, circuit-breaker, per-call fallback to the simulator, with
                     provenance on every payload (the UI shows LIVE vs SIMULATED).
"""
from __future__ import annotations

import re
import threading
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import UNIVERSE

SECTOR = {
    "AAPL": "Consumer Hardware", "MSFT": "Software", "NVDA": "Semiconductors", "GOOGL": "Internet",
    "AMZN": "E-commerce/Cloud", "META": "Internet", "TSLA": "Autos/Energy", "AMD": "Semiconductors",
    "AVGO": "Semiconductors", "ADBE": "Software", "INTC": "Semiconductors", "QCOM": "Semiconductors",
    "NFLX": "Media", "CSCO": "Networking", "INTU": "Software", "PANW": "Cybersecurity",
}
# (start price, annual drift, annual vol, market beta, revenue $bn TTM) - illustrative only
_PARAMS = {
    "AAPL": (130, .12, .26, 1.0, 390), "MSFT": (225, .16, .27, 1.1, 245), "NVDA": (130, .45, .55, 1.7, 90),
    "GOOGL": (88, .13, .29, 1.1, 300), "AMZN": (95, .14, .33, 1.3, 570), "META": (110, .20, .42, 1.4, 135),
    "TSLA": (220, .10, .60, 1.8, 95), "AMD": (65, .22, .50, 1.6, 24), "AVGO": (45, .30, .38, 1.3, 40),
    "ADBE": (330, .05, .34, 1.1, 20), "INTC": (30, -.12, .40, 1.2, 55), "QCOM": (115, .06, .36, 1.2, 38),
    "NFLX": (300, .18, .42, 1.2, 35), "CSCO": (47, .05, .22, .8, 57), "INTU": (400, .10, .32, 1.1, 16),
    "PANW": (150, .18, .40, 1.2, 8),
}
_ANCHOR = date(2021, 1, 4)


class ProviderError(RuntimeError):
    def __init__(self, msg: str, transient: bool = True):
        super().__init__(msg)
        self.transient = transient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def provenance(source: str, simulated: bool, as_of: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    return {"source": source, "simulated": simulated, "as_of": as_of or _now(),
            "fetched_at": _now(), "note": note}


class SyntheticProvider:
    name = "synthetic"

    def __init__(self, today: Optional[date] = None):
        self._today = today
        self._cache: Dict[str, pd.DataFrame] = {}
        self._lock = threading.Lock()

    def today(self) -> date:
        return self._today or date.today()

    def _series(self, symbol: str) -> pd.DataFrame:
        key = f"{symbol}:{self.today()}"
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        p = _PARAMS.get(symbol)
        if p is None:  # unknown ticker: deterministic pseudo-params
            h = zlib.crc32(symbol.encode())
            p = (20 + h % 300, .08, .30 + (h % 20) / 100, 1.0, 5 + h % 50)
        start, mu, sig, beta, _ = p
        days = pd.bdate_range(_ANCHOR, self.today())
        n = len(days)
        mkt_rng = np.random.RandomState(7)
        # market factor with volatility regimes -> realistic cross-correlation and drawdowns
        regime = np.repeat(mkt_rng.choice([.8, 1.0, 1.9], size=n // 60 + 1, p=[.45, .4, .15]), 60)[:n]
        mkt = mkt_rng.normal(0.0004, 0.009, n) * regime
        rng = np.random.RandomState(zlib.crc32(symbol.encode()) & 0x7FFFFFFF)
        idio_sig = max(sig / np.sqrt(252) * 0.75, 0.002)
        ret = mu / 252 + beta * (mkt - 0.0004) + rng.normal(0, idio_sig, n)
        logp = np.cumsum(ret)
        # detrend so the realised CAGR equals a sane target; keeps vol/shape, avoids absurd compounding
        target = float(np.clip(mu, -0.10, 0.25)) * n / 252
        logp = logp - np.linspace(0, 1, n) * (logp[-1] - target)
        close = start * np.exp(logp)
        prev = np.concatenate([[start], close[:-1]])
        gap = rng.normal(0, idio_sig * 0.35, n)
        open_ = prev * (1 + gap)
        rng_hl = np.abs(rng.normal(0, idio_sig * 0.8, n)) + 0.002
        high = np.maximum(open_, close) * (1 + rng_hl)
        low = np.minimum(open_, close) * (1 - rng_hl)
        base_vol = 2e7 + (zlib.crc32(symbol.encode()) % 80) * 1e6
        vol = base_vol * np.exp(rng.normal(0, .25, n)) * (1 + 18 * np.abs(ret))
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in days],
            "open": open_.round(2), "high": high.round(2), "low": low.round(2),
            "close": close.round(2), "volume": vol.astype("int64"),
        })
        with self._lock:
            self._cache = {k: v for k, v in self._cache.items() if k.endswith(str(self.today()))}
            self._cache[key] = df
        return df

    def history(self, symbol: str, days: int = 180) -> Dict[str, Any]:
        df = self._series(symbol).tail(days)
        return {"symbol": symbol, "candles": df.to_dict("records"),
                "provenance": provenance("synthetic", True, df.iloc[-1]["date"],
                                         "Seeded simulator - not market data")}

    def quote(self, symbol: str) -> Dict[str, Any]:
        df = self._series(symbol)
        last, prev = df.iloc[-1], df.iloc[-2]
        chg = float(last["close"] - prev["close"])
        return {"symbol": symbol, "price": float(last["close"]), "change": round(chg, 2),
                "change_pct": round(chg / float(prev["close"]) * 100, 2), "volume": int(last["volume"]),
                "provenance": provenance("synthetic", True, last["date"], "Seeded simulator - not market data")}

    def fundamentals(self, symbol: str) -> Dict[str, Any]:
        p = _PARAMS.get(symbol) or (50, .08, .3, 1.0, 10)
        rng = np.random.RandomState(zlib.crc32(("f" + symbol).encode()) & 0x7FFFFFFF)
        rev_ttm = p[4] * 1e9
        growth = float(np.clip(p[1] * 0.8 + rng.normal(0, .03), -.1, .6))
        gm = float(np.clip(rng.normal(.55, .15), .25, .8))
        om = float(np.clip(gm - rng.uniform(.12, .3), -.05, .5))
        nm = float(np.clip(om - rng.uniform(.0, .05), -.05, .45))
        q_rev, q_ni, q_eps, quarters = [], [], [], []
        shares = max(rev_ttm * nm / max(rng.uniform(2, 9), 1), 1e8) / rng.uniform(2, 9) + 5e8
        r = rev_ttm / 4 / (1 + growth) ** 1.75
        today = self.today()
        for i in range(8):
            r *= (1 + growth) ** 0.25 * (1 + rng.normal(0, .015))
            ni = r * nm * (1 + rng.normal(0, .05))
            q_rev.append(round(r / 1e9, 2)); q_ni.append(round(ni / 1e9, 2))
            q_eps.append(round(ni / shares, 2))
            qd = today - timedelta(days=90 * (7 - i))
            quarters.append(f"{qd.year}Q{(qd.month - 1) // 3 + 1}")
        price = float(self._series(symbol).iloc[-1]["close"])
        eps_ttm = float(sum(q_eps[-4:]))
        pe = round(price / eps_ttm, 1) if eps_ttm > 0 else None
        mcap = price * shares
        cash = rev_ttm * rng.uniform(.1, .35)
        debt = rev_ttm * rng.uniform(.05, .4)
        equity = rev_ttm * rng.uniform(.3, 1.2)
        fcf = rev_ttm * nm * rng.uniform(.8, 1.3)
        ratios = {
            "pe": pe, "forward_pe": round(pe / (1 + growth), 1) if pe else None,
            "ps": round(mcap / rev_ttm, 2), "market_cap": round(mcap),
            "revenue_growth_yoy": round(growth, 3), "gross_margin": round(gm, 3),
            "operating_margin": round(om, 3), "net_margin": round(nm, 3),
            "fcf_yield": round(fcf / mcap, 4), "debt_to_equity": round(debt / equity, 2),
            "roe": round(rev_ttm * nm / equity, 3), "beta": p[3], "eps_ttm": round(eps_ttm, 2),
        }
        statements = {"quarters": quarters, "revenue_bn": q_rev, "net_income_bn": q_ni, "eps": q_eps,
                      "cash_bn": round(cash / 1e9, 1), "debt_bn": round(debt / 1e9, 1), "fcf_bn": round(fcf / 1e9, 1)}
        return {"symbol": symbol, "sector": SECTOR.get(symbol, "Technology"), "ratios": ratios,
                "statements": statements, "fields_source": {k: "synthetic" for k in ratios},
                "provenance": provenance("synthetic", True, str(today), "Simulated statements - not reported figures")}


class NasdaqProvider:
    """Parses api.nasdaq.com. Endpoint shapes are unofficial and may change - keep parsers tolerant."""
    name = "nasdaq"
    BASE = "https://api.nasdaq.com/api"
    HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
               "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
               "Referer": "https://www.nasdaq.com/"}

    def __init__(self, timeout_s: float = 4.0, client=None):
        import httpx
        self._client = client or httpx.Client(timeout=timeout_s, headers=self.HEADERS)

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.time()
        try:
            r = self._client.get(f"{self.BASE}{path}", params=params)
            r.raise_for_status()
            body = r.json()
        except Exception as e:  # network, HTTP, JSON
            raise ProviderError(f"nasdaq {path}: {type(e).__name__}: {e}") from e
        if not isinstance(body, dict) or body.get("status", {}).get("rCode") not in (200, None) or not body.get("data"):
            raise ProviderError(f"nasdaq {path}: empty/err payload", transient=False)
        body["_latency_ms"] = int((time.time() - t0) * 1000)
        return body

    @staticmethod
    def num(s: Any) -> Optional[float]:
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return float(s)
        m = re.sub(r"[^0-9.\-]", "", str(s).replace("N/A", ""))
        try:
            return float(m) if m not in ("", "-", ".") else None
        except ValueError:
            return None

    def quote(self, symbol: str) -> Dict[str, Any]:
        body = self._get(f"/quote/{symbol}/info", {"assetclass": "stocks"})
        pd_ = (body["data"] or {}).get("primaryData") or {}
        price = self.num(pd_.get("lastSalePrice"))
        if price is None:
            raise ProviderError("nasdaq quote: no price", transient=False)
        return {"symbol": symbol, "price": price, "change": self.num(pd_.get("netChange")) or 0.0,
                "change_pct": self.num(pd_.get("percentageChange")) or 0.0,
                "volume": int(self.num(pd_.get("volume")) or 0),
                "provenance": provenance("nasdaq", False, pd_.get("lastTradeTimestamp"),
                                         f"latency {body['_latency_ms']}ms; Nasdaq data may be delayed")}

    def history(self, symbol: str, days: int = 180) -> Dict[str, Any]:
        frm = (date.today() - timedelta(days=int(days * 1.6) + 10)).isoformat()
        body = self._get(f"/quote/{symbol}/historical",
                         {"assetclass": "stocks", "fromdate": frm, "todate": date.today().isoformat(), "limit": 9999})
        rows = ((body["data"] or {}).get("tradesTable") or {}).get("rows") or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                d = datetime.strptime(r["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
                out.append({"date": d, "open": self.num(r["open"]), "high": self.num(r["high"]),
                            "low": self.num(r["low"]), "close": self.num(r["close"]),
                            "volume": int(self.num(r["volume"]) or 0)})
            except (KeyError, ValueError, TypeError):
                continue
        out = [c for c in out if None not in (c["open"], c["high"], c["low"], c["close"])]
        if len(out) < 30:
            raise ProviderError("nasdaq history: too few rows", transient=False)
        out.sort(key=lambda c: c["date"])
        return {"symbol": symbol, "candles": out[-days:],
                "provenance": provenance("nasdaq", False, out[-1]["date"], f"latency {body['_latency_ms']}ms")}

    def fundamentals(self, symbol: str) -> Dict[str, Any]:
        body = self._get(f"/quote/{symbol}/summary", {"assetclass": "stocks"})
        sd = (body["data"] or {}).get("summaryData") or {}
        g = lambda k: self.num((sd.get(k) or {}).get("value"))  # noqa: E731
        ratios = {"pe": g("PERatio"), "forward_pe": g("ForwardPE1Yr"), "market_cap": g("MarketCap"),
                  "eps_ttm": g("EarningsPerShare"), "beta": g("Beta"), "dividend_yield": g("Yield")}
        ratios = {k: v for k, v in ratios.items() if v is not None}
        if not ratios:
            raise ProviderError("nasdaq summary: no ratios", transient=False)
        sector = ((sd.get("Sector") or {}).get("value")) or SECTOR.get(symbol, "Technology")
        return {"symbol": symbol, "sector": sector, "ratios": ratios, "statements": None,
                "fields_source": {k: "nasdaq" for k in ratios},
                "provenance": provenance("nasdaq", False, None, "Summary ratios only")}


class AutoProvider:
    """Nasdaq-first with circuit breaker; falls back per call to the simulator."""
    name = "auto"

    def __init__(self, primary: Optional[NasdaqProvider], fallback: SyntheticProvider, ttl_s: float = 20.0,
                 breaker_threshold: int = 3, breaker_cooldown_s: float = 60.0):
        self.primary, self.fallback = primary, fallback
        self.ttl_s, self._th, self._cool = ttl_s, breaker_threshold, breaker_cooldown_s
        self._fails, self._open_until = 0, 0.0
        self._cache: Dict[Any, Any] = {}
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None

    @property
    def breaker_open(self) -> bool:
        return time.time() < self._open_until

    def _call(self, method: str, *args) -> Dict[str, Any]:
        key = (method, args)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.ttl_s:
                return hit[1]
        res = None
        if self.primary is not None and not self.breaker_open:
            try:
                res = getattr(self.primary, method)(*args)
                self._fails = 0
            except ProviderError as e:
                self.last_error = str(e)
                self._fails += 1
                if self._fails >= self._th:
                    self._open_until = time.time() + self._cool
        if res is None:
            res = getattr(self.fallback, method)(*args)
            if self.primary is not None:
                res["provenance"]["note"] += f" | fallback: {self.last_error or 'breaker open'}"
        elif method == "fundamentals":  # enrich partial Nasdaq ratios with simulated statements, tag per field
            sim = self.fallback.fundamentals(*args)
            merged = dict(sim["ratios"]); merged.update(res["ratios"])
            src = dict(sim["fields_source"]); src.update(res["fields_source"])
            res = {**res, "ratios": merged, "statements": sim["statements"], "fields_source": src}
            res["provenance"] = {**res["provenance"], "simulated": False, "mixed": True,
                                 "note": "Ratios from Nasdaq where available; statements are SIMULATED"}
        with self._lock:
            self._cache[key] = (time.time(), res)
        return res

    def quote(self, s): return self._call("quote", s)
    def history(self, s, days=180): return self._call("history", s, days)
    def fundamentals(self, s): return self._call("fundamentals", s)


def build_provider(settings) -> Any:
    sim = SyntheticProvider()
    if settings.provider == "synthetic":
        return sim
    nas = NasdaqProvider(settings.nasdaq_timeout_s)
    if settings.provider == "nasdaq":
        return nas
    return AutoProvider(nas, sim)


def history_df(h: Dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(h["candles"])


__all__ = ["UNIVERSE", "SECTOR", "ProviderError", "SyntheticProvider", "NasdaqProvider", "AutoProvider",
           "build_provider", "history_df", "provenance"]
