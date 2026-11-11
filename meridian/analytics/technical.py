"""Technical analysis: indicators, trend, patterns, support/resistance, volatility regime."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    d = close.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0).where(au.notna())


def macd(close: pd.Series, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = line.ewm(span=sig, adjust=False, min_periods=sig).mean()
    return line, signal, line - signal


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def atr(df: pd.DataFrame, n=14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    for n in (20, 50, 200):
        d[f"sma{n}"] = sma(c, n)
    d["ema12"], d["ema26"] = ema(c, 12), ema(c, 26)
    d["rsi14"] = rsi(c)
    d["macd"], d["macd_signal"], d["macd_hist"] = macd(c)
    d["bb_low"], d["bb_mid"], d["bb_up"] = bollinger(c)
    d["atr14"] = atr(d)
    d["obv"] = obv(d)
    d["vol_sma20"] = sma(d["volume"].astype(float), 20)
    return d


def detect_patterns(df: pd.DataFrame) -> List[str]:
    """Candlestick patterns on the last 2 bars."""
    if len(df) < 3:
        return []
    a, b = df.iloc[-2], df.iloc[-1]
    body = abs(b.close - b.open)
    rng = max(b.high - b.low, 1e-9)
    upper, lower = b.high - max(b.open, b.close), min(b.open, b.close) - b.low
    out = []
    if body / rng < 0.1:
        out.append("doji")
    if lower > 2 * body and upper < 0.3 * rng and body / rng > 0.05:
        out.append("hammer")
    if upper > 2 * body and lower < 0.3 * rng and body / rng > 0.05:
        out.append("shooting_star")
    if a.close < a.open and b.close > b.open and b.close >= a.open and b.open <= a.close:
        out.append("bullish_engulfing")
    if a.close > a.open and b.close < b.open and b.open >= a.close and b.close <= a.open:
        out.append("bearish_engulfing")
    return out


def classify_trend(price: float, s20: float, s50: float, s200: float) -> str:
    vals = [s20, s50, s200]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        if not np.isnan(s20) and not np.isnan(s50):
            return "uptrend" if price > s20 > s50 else "downtrend" if price < s20 < s50 else "sideways"
        return "insufficient_data"
    if price > s20 > s50 > s200:
        return "strong_uptrend"
    if price < s20 < s50 < s200:
        return "strong_downtrend"
    if price > s50 and s50 > s200:
        return "uptrend"
    if price < s50 and s50 < s200:
        return "downtrend"
    return "sideways"


def support_resistance(df: pd.DataFrame, window: int = 5, tol: float = 0.015, lookback: int = 250) -> Dict[str, Any]:
    d = df.tail(lookback).reset_index(drop=True)
    hi, lo = d["high"].values, d["low"].values
    piv_hi = [hi[i] for i in range(window, len(d) - window) if hi[i] == hi[i - window:i + window + 1].max()]
    piv_lo = [lo[i] for i in range(window, len(d) - window) if lo[i] == lo[i - window:i + window + 1].min()]

    def cluster(levels):
        out: List[List[float]] = []
        for lv in sorted(levels):
            if out and abs(lv - np.mean(out[-1])) / np.mean(out[-1]) < tol:
                out[-1].append(lv)
            else:
                out.append([lv])
        return sorted([(float(np.mean(c)), len(c)) for c in out], key=lambda x: -x[1])

    price = float(d["close"].iloc[-1])
    levels = cluster(piv_hi + piv_lo)
    below = sorted([l for l, _ in levels if l < price], reverse=True)[:2]
    above = sorted([l for l, _ in levels if l > price])[:2]
    return {"support": [round(x, 2) for x in below], "resistance": [round(x, 2) for x in above]}


def volatility_regime(df: pd.DataFrame) -> Dict[str, Any]:
    ret = df["close"].pct_change()
    rv = ret.rolling(20).std() * np.sqrt(252)
    cur = float(rv.iloc[-1]) if not np.isnan(rv.iloc[-1]) else float("nan")
    hist = rv.dropna().tail(504)
    pct = float((hist < cur).mean() * 100) if len(hist) > 30 and not np.isnan(cur) else 50.0
    s50 = df["close"].rolling(50).mean().iloc[-1]
    s200 = df["close"].rolling(200).mean().iloc[-1]
    bull = bool(df["close"].iloc[-1] > s50) if not np.isnan(s50) else True
    if not np.isnan(s200):
        bull = bull and bool(s50 > s200 or df["close"].iloc[-1] > s200)
    calm = pct < 60
    label = ("Calm Bull" if calm else "Volatile Bull") if bull else ("Quiet Bear" if calm else "Stress / Bear")
    return {"label": label, "vol_20d_ann": round(cur, 3) if not np.isnan(cur) else None, "vol_percentile": round(pct, 0)}


def tech_score(s: Dict[str, Any]) -> float:
    """0-100 composite: trend, momentum, mean-reversion room, volume confirmation."""
    score = 50.0
    score += {"strong_uptrend": 18, "uptrend": 10, "sideways": 0, "downtrend": -10, "strong_downtrend": -18}.get(s["trend"], 0)
    r = s.get("rsi14")
    if r is not None:
        if r < 30: score += 8          # oversold: potential bounce
        elif r > 75: score -= 10        # stretched
        elif 50 <= r <= 65: score += 6  # healthy momentum
    if s.get("macd_hist") is not None:
        score += 6 if s["macd_hist"] > 0 else -6
    if s.get("ret_3m") is not None:
        score += float(np.clip(s["ret_3m"] * 40, -10, 10))
    if s.get("volume_ratio", 1) > 1.3 and s.get("ret_1d", 0) > 0:
        score += 4
    if s.get("max_dd_6m") is not None and s["max_dd_6m"] < -0.25:
        score -= 6
    return float(np.clip(score, 0, 100))


def snapshot(df: pd.DataFrame) -> Dict[str, Any]:
    d = add_indicators(df)
    last = d.iloc[-1]
    price = float(last.close)
    c = d["close"]

    def f(x, nd=2):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)

    ret = lambda n: float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None  # noqa: E731
    roll_max = c.tail(126).cummax()
    snap = {
        "price": f(price), "ret_1d": f(ret(1), 4), "ret_1m": f(ret(21), 4), "ret_3m": f(ret(63), 4),
        "ret_6m": f(ret(126), 4), "rsi14": f(last.rsi14, 1), "macd_hist": f(last.macd_hist, 3),
        "sma20": f(last.sma20), "sma50": f(last.sma50), "sma200": f(last.sma200),
        "bb_pos": f((price - last.bb_low) / (last.bb_up - last.bb_low), 2) if not np.isnan(last.bb_up) else None,
        "atr_pct": f(last.atr14 / price, 4), "vol_20d_ann": volatility_regime(d)["vol_20d_ann"],
        "volume_ratio": f(last.volume / last.vol_sma20, 2) if not np.isnan(last.vol_sma20) else 1.0,
        "max_dd_6m": f(float((c.tail(126) / roll_max - 1).min()), 3),
        "trend": classify_trend(price, last.sma20, last.sma50, last.sma200),
        "patterns": detect_patterns(d), "regime": volatility_regime(d),
        "levels": support_resistance(d),
        "as_of": str(last["date"]),
    }
    snap["tech_score"] = round(tech_score(snap), 1)
    return snap


def indicator_series(df: pd.DataFrame, cols=None) -> Dict[str, List[Any]]:
    d = add_indicators(df)
    cols = cols or ["sma20", "sma50", "sma200", "bb_low", "bb_mid", "bb_up", "rsi14", "macd", "macd_signal", "macd_hist"]
    out: Dict[str, List[Any]] = {"date": d["date"].tolist()}
    for c in cols:
        out[c] = [None if np.isnan(v) else round(float(v), 4) for v in d[c]]
    return out
