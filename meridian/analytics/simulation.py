"""Numerical engines: Monte-Carlo projection, portfolio what-if, RSI back-test."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .technical import rsi


def monte_carlo(returns: np.ndarray, start: float, horizon: int = 126, paths: int = 2000,
                seed: int = 42, method: str = "bootstrap") -> Dict[str, Any]:
    """Percentile fan of future value. `bootstrap` resamples historical daily returns."""
    rng = np.random.RandomState(seed)
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 30:
        raise ValueError("need >=30 return observations")
    if method == "gbm":
        draws = rng.normal(r.mean(), r.std(ddof=1), size=(paths, horizon))
    else:
        draws = rng.choice(r, size=(paths, horizon), replace=True)
    value = start * np.cumprod(1 + draws, axis=1)
    qs = {"p5": 5, "p25": 25, "p50": 50, "p75": 75, "p95": 95}
    bands = {k: np.percentile(value, q, axis=0).round(2).tolist() for k, q in qs.items()}
    final = value[:, -1]
    return {"bands": bands, "horizon": horizon, "paths": paths, "method": method,
            "prob_gain": round(float((final > start).mean()), 3),
            "expected_final": round(float(final.mean()), 2),
            "var95_pct": round(float(np.percentile(final / start - 1, 5)), 4)}


def portfolio_stats(weights: Dict[str, float], prices: pd.DataFrame, rf: float = 0.04) -> Dict[str, Any]:
    """`prices` = DataFrame of closes, one column per symbol."""
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    rets = prices[w.index].pct_change().dropna()
    pr = rets @ w
    mu, sd = pr.mean() * 252, pr.std(ddof=1) * np.sqrt(252)
    cov = rets.cov() * 252
    port_var = float(w.values @ cov.values @ w.values)
    mrc = cov.values @ w.values
    rc = (w.values * mrc) / port_var if port_var > 0 else np.zeros(len(w))
    equity = (1 + pr).cumprod()
    dd = equity / equity.cummax() - 1
    return {
        "weights": {k: round(float(v), 4) for k, v in w.items()},
        "ann_return": round(float(mu), 4), "ann_vol": round(float(sd), 4),
        "sharpe": round(float((mu - rf) / sd), 2) if sd > 0 else None,
        "var95_1d": round(float(np.percentile(pr, 5)), 4), "max_drawdown": round(float(dd.min()), 4),
        "risk_contribution": {k: round(float(v), 3) for k, v in zip(w.index, rc)},
        "diversification_ratio": round(float((w.values * np.sqrt(np.diag(cov.values))).sum() / np.sqrt(port_var)), 2)
        if port_var > 0 else None,
        "correlation": rets.corr().round(2).values.tolist(), "symbols": list(w.index),
    }


def backtest_rsi(df: pd.DataFrame, entry: float = 30, exit_: float = 55, max_hold: int = 20,
                 cost_bps: float = 5.0) -> Dict[str, Any]:
    """Long-only mean-reversion: buy next open after RSI<entry, exit at RSI>exit or max_hold days."""
    d = df.reset_index(drop=True).copy()
    d["rsi"] = rsi(d["close"])
    trades: List[Dict[str, Any]] = []
    i, n = 15, len(d)
    while i < n - 2:
        if d.at[i, "rsi"] < entry:
            e_i = i + 1
            entry_px = float(d.at[e_i, "open"])
            x_i = min(e_i + max_hold, n - 1)
            for j in range(e_i + 1, min(e_i + max_hold, n - 1) + 1):
                if d.at[j, "rsi"] > exit_:
                    x_i = j
                    break
            exit_px = float(d.at[x_i, "close"])
            ret = exit_px / entry_px - 1 - 2 * cost_bps / 1e4
            trades.append({"entry_date": d.at[e_i, "date"], "exit_date": d.at[x_i, "date"],
                           "ret": round(ret, 4), "bars": int(x_i - e_i)})
            i = x_i + 1
        else:
            i += 1
    rets = np.array([t["ret"] for t in trades])
    bh = float(d["close"].iloc[-1] / d["close"].iloc[15] - 1)
    return {
        "trades": len(trades), "win_rate": round(float((rets > 0).mean()), 3) if len(rets) else None,
        "avg_trade": round(float(rets.mean()), 4) if len(rets) else None,
        "total_compounded": round(float(np.prod(1 + rets) - 1), 4) if len(rets) else 0.0,
        "buy_hold": round(bh, 4), "params": {"entry": entry, "exit": exit_, "max_hold": max_hold, "cost_bps": cost_bps},
        "last_trades": trades[-5:],
        "caveat": "In-sample, single-asset, long-only; no slippage model beyond fixed cost. Illustrative.",
    }
