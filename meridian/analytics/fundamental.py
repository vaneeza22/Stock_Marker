"""Fundamental analysis: quality / valuation / growth scoring on provider fundamentals."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def fund_snapshot(f: Dict[str, Any]) -> Dict[str, Any]:
    r = f["ratios"]
    flags: List[str] = []
    pe = r.get("pe")
    growth = r.get("revenue_growth_yoy")
    peg = round(pe / (growth * 100), 2) if pe and growth and growth > 0 else None
    if pe is None:
        flags.append("no_positive_earnings")
    elif pe > 45:
        flags.append("rich_valuation")
    elif pe < 15:
        flags.append("cheap_vs_market")
    if (r.get("debt_to_equity") or 0) > 1.5:
        flags.append("leveraged")
    if (r.get("operating_margin") or 0) > 0.30:
        flags.append("high_margin")
    if growth is not None and growth > 0.20:
        flags.append("high_growth")
    if growth is not None and growth < 0:
        flags.append("shrinking_revenue")

    # sub-scores (0..1). Missing inputs are neutral so partial Nasdaq data does not distort ranking.
    val = 0.5 if pe is None else _clip01(1 - (pe - 12) / 50) if pe > 0 else 0.1
    gro = 0.5 if growth is None else _clip01((growth + 0.05) / 0.35)
    qual_parts = [x for x in (
        _clip01((r.get("operating_margin") or 0) / 0.4) if r.get("operating_margin") is not None else None,
        _clip01(1 - (r.get("debt_to_equity") or 0) / 3) if r.get("debt_to_equity") is not None else None,
        _clip01((r.get("roe") or 0) / 0.35) if r.get("roe") is not None else None,
    ) if x is not None]
    qual = float(np.mean(qual_parts)) if qual_parts else 0.5
    score = round(100 * (0.35 * qual + 0.35 * gro + 0.30 * val), 1)
    return {"pe": pe, "forward_pe": r.get("forward_pe"), "peg": peg, "ps": r.get("ps"),
            "revenue_growth_yoy": growth, "net_margin": r.get("net_margin"),
            "operating_margin": r.get("operating_margin"), "fcf_yield": r.get("fcf_yield"),
            "debt_to_equity": r.get("debt_to_equity"), "roe": r.get("roe"), "beta": r.get("beta"),
            "market_cap": r.get("market_cap"), "flags": flags,
            "subscores": {"quality": round(qual * 100), "growth": round(gro * 100), "valuation": round(val * 100)},
            "fund_score": score, "sector": f.get("sector"),
            "simulated_fields": sorted(k for k, v in f.get("fields_source", {}).items() if v == "synthetic")}
