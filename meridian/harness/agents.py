"""Debate layer: three specialist personas (Bull, Bear, Risk) argue from the same structured signals,
then a deterministic arbiter produces a Decision Card (stance, conviction, 'what would change my mind').
Rule-based so every claim is traceable to a number; an LLM may only rephrase the narrative."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def bull_case(s: Dict[str, Any]) -> List[str]:
    out = []
    if s.get("trend") in ("uptrend", "strong_uptrend"):
        out.append(f"Trend is {s['trend'].replace('_', ' ')} (price above rising averages).")
    if s.get("rsi") is not None and s["rsi"] < 35:
        out.append(f"RSI {s['rsi']:.0f} is oversold - historically a mean-reversion entry zone.")
    elif s.get("rsi") is not None and 50 <= s["rsi"] <= 65:
        out.append(f"RSI {s['rsi']:.0f} shows healthy, non-stretched momentum.")
    if (s.get("growth") or 0) > 0.15:
        out.append(f"Revenue growing {_pct(s['growth'])} YoY.")
    if "high_margin" in (s.get("flags") or []):
        out.append("Operating margin above 30% signals pricing power.")
    if (s.get("macd_hist") or 0) > 0:
        out.append("MACD histogram positive - momentum improving.")
    if (s.get("fund_score") or 0) >= 60:
        out.append(f"Fundamental score {s['fund_score']:.0f}/100 is solid.")
    if (s.get("ret_3m") or 0) > 0.08:
        out.append(f"3-month return {_pct(s['ret_3m'])} confirms relative strength.")
    return out or ["No strong positive factor stands out."]


def bear_case(s: Dict[str, Any]) -> List[str]:
    out = []
    if s.get("trend") in ("downtrend", "strong_downtrend"):
        out.append(f"Trend is {s['trend'].replace('_', ' ')} - catching a falling knife.")
    if (s.get("rsi") or 0) > 70:
        out.append(f"RSI {s['rsi']:.0f} is overbought; pullback risk is elevated.")
    if "rich_valuation" in (s.get("flags") or []):
        out.append(f"Valuation is rich (P/E {s.get('pe')}) - leaves little margin for error.")
    if "shrinking_revenue" in (s.get("flags") or []):
        out.append("Revenue is shrinking YoY.")
    if "leveraged" in (s.get("flags") or []):
        out.append("Balance sheet is leveraged (D/E > 1.5).")
    if "no_positive_earnings" in (s.get("flags") or []):
        out.append("No positive trailing earnings; valuation rests on future promises.")
    if (s.get("macd_hist") or 0) < 0:
        out.append("MACD histogram negative - momentum fading.")
    if (s.get("tech_score") or 50) < 40:
        out.append(f"Technical score only {s['tech_score']:.0f}/100.")
    return out or ["No acute red flag in the data reviewed."]


def risk_case(s: Dict[str, Any]) -> List[str]:
    out = []
    if (s.get("vol") or 0) > 0.45:
        out.append(f"Realised volatility {s['vol'] * 100:.0f}% annualised - size down.")
    if (s.get("max_dd") or 0) < -0.2:
        out.append(f"Drawdown of {s['max_dd'] * 100:.0f}% within 6 months shows fragility.")
    if "Stress" in (s.get("regime") or "") or "Volatile" in (s.get("regime") or ""):
        out.append(f"Regime is '{s['regime']}' - correlations tend to rise and stops get gapped.")
    if (s.get("beta") or 1) > 1.5:
        out.append(f"Beta {s['beta']} amplifies market moves.")
    if (s.get("weight") or 0) > 0.35:
        out.append(f"Position weight {s['weight'] * 100:.0f}% breaches a 35% concentration guide.")
    if s.get("simulated"):
        out.append("Some inputs are SIMULATED (provider fallback) - treat conclusions as illustrative.")
    return out or ["Risk metrics within normal bands."]


def arbitrate(s: Dict[str, Any], capital_nav: float = 100_000) -> Dict[str, Any]:
    bull, bear, risk = bull_case(s), bear_case(s), risk_case(s)
    real_bear = [b for b in bear if not b.startswith("No acute")]
    real_bull = [b for b in bull if not b.startswith("No strong")]
    real_risk = [r for r in risk if not r.startswith("Risk metrics")]
    base = 0.55 * (s.get("tech_score") or 50) + 0.45 * (s.get("fund_score") or 50)
    conviction = float(np.clip(base - 4 * len(real_risk) + 2 * (len(real_bull) - len(real_bear)), 0, 100))
    stance = "Constructive" if conviction >= 60 else "Cautious" if conviction <= 42 else "Neutral"
    price, sup = s.get("price"), s.get("support")
    triggers = []
    if sup:
        triggers.append({"if": f"Closes below support {sup}", "then": "Thesis invalidated - re-run analysis before acting."})
    if s.get("rsi") is not None:
        triggers.append({"if": "RSI crosses above 70" if s["rsi"] < 70 else "RSI falls back below 60",
                         "then": "Momentum stretched - trim/pause adds." if s["rsi"] < 70 else "Overbought pressure easing."})
    if s.get("resistance"):
        triggers.append({"if": f"Breaks above resistance {s['resistance']} on high volume", "then": "Upgrade conviction."})
    triggers.append({"if": "Next earnings guide differs from simulated/assumed growth", "then": "Refresh fundamentals."})
    qty = int(max(1, (0.02 * capital_nav) / price)) if price else None
    action = {"type": "paper_trade_candidate", "side": "buy", "suggested_qty": qty,
              "sizing_note": "2% of a $100k reference NAV (illustrative)"} if stance == "Constructive" and qty else {"type": "watch"}
    return {"symbol": s["symbol"], "stance": stance, "conviction": round(conviction), "bull": bull, "bear": bear, "risk": risk,
            "triggers": triggers, "action": action, "price": price, "debate_margin": len(real_bull) - len(real_bear)}


def pick_focus(signals: List[Dict[str, Any]], intent: str, limit: int = 3) -> List[Dict[str, Any]]:
    if intent in ("analyze", "backtest"):
        return signals[:1]
    if intent in ("whatif", "book"):
        return sorted(signals, key=lambda s: -(s.get("weight") or 0))[:limit]
    return sorted(signals, key=lambda s: -(0.55 * (s.get("tech_score") or 0) + 0.45 * (s.get("fund_score") or 0)))[:limit] \
        if intent in ("screen", "overview") else signals[:limit]


def decision_cards(signals: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    return [arbitrate(s) for s in pick_focus(signals, intent)]


def explain(prompt: str, plan_intent: str, result: Dict[str, Any], cards: List[Dict[str, Any]],
            metrics: List[Dict[str, Any]], prov: List[Dict[str, Any]], notes: List[str], llm=None) -> str:
    sim = any(p.get("simulated") for p in prov)
    parts: List[str] = []
    r = result or {}
    if plan_intent == "screen":
        picks = ", ".join(r.get("picks", [])) or "none"
        parts.append(f"**Screen result** - rule `{r.get('rule')}` " + ("matched nothing, so I show the closest names instead. "
                     if r.get("relaxed") else "produced these names: ") + f"**{picks}**.")
        parts.append(f"A hypothetical inverse-volatility basket has a {r.get('prob_gain', 0) * 100:.0f}% bootstrap probability of gaining over "
                     f"6 months, with a 5th-percentile outcome of {r.get('var95_pct', 0) * 100:.1f}% (median ${r.get('median_final', 0):,.0f}).")
    elif plan_intent == "analyze":
        parts.append(f"**{r.get('symbol')}** - bootstrap projection gives a {r.get('prob_gain_3m', 0) * 100:.0f}% chance of being higher in 3 months; "
                     f"the RSI<30 rule made {r.get('backtest', {}).get('trades')} trades (compounded {_pct(r.get('backtest', {}).get('total'))} vs "
                     f"buy & hold {_pct(r.get('backtest', {}).get('buy_hold'))}).")
    elif plan_intent == "compare":
        parts.append(f"**Comparison** of {', '.join(r.get('symbols', []))}: the composite leader is **{r.get('leader')}**; "
                     f"average pairwise correlation is {r.get('avg_pair_corr')} (diversification benefit shrinks as this rises).")
    elif plan_intent == "whatif":
        parts.append(f"**What-if** - {', '.join(f'{k} {v * 100:.0f}%' for k, v in r.get('weights', {}).items())}: historical vol "
                     f"{r.get('ann_vol', 0) * 100:.0f}%, Sharpe {r.get('sharpe')}, max drawdown {r.get('max_dd', 0) * 100:.0f}%, beta {r.get('beta')}; "
                     f"largest risk contributor **{r.get('top_risk')}**. P(gain over horizon) {r.get('prob_gain', 0) * 100:.0f}%, 5th-percentile {r.get('var95_pct', 0) * 100:.1f}%.")
    elif plan_intent == "overview":
        parts.append(f"**Market read** - breadth {r.get('breadth', 0) * 100:.0f}% above SMA50, dominant regime *{r.get('regime')}*. "
                     f"Leaders: {', '.join(r.get('leaders', []))}. Laggards: {', '.join(r.get('laggards', []))}.")
    elif plan_intent == "book":
        parts.append(f"**Paper book** ${r.get('total', 0):,.0f}; largest position {r.get('top')}, concentration HHI {r.get('hhi')}.")
    elif plan_intent == "backtest":
        parts.append(f"**Back-test** {r.get('symbol')}: best entry threshold RSI<{r.get('best_entry')}; edge vs buy & hold {_pct(r.get('edge_vs_hold'))} (in-sample).")
    elif plan_intent == "propose":
        parts.append(f"Approval request `{r.get('approval_id')}` is **{r.get('status')}** - nothing was executed. A human must approve it in the Approvals panel.")
    for c in cards[:3]:
        parts.append(f"- **{c['symbol']}** → *{c['stance']}* (conviction {c['conviction']}/100). Bull: {c['bull'][0]} Bear: {c['bear'][0]}")
    parts.extend(f"> {n}" for n in notes[:3])
    parts.append("_Data: " + ("**SIMULATED** (Nasdaq unavailable or fundamentals filled by the simulator) - illustrative only. "
                 if sim else "Nasdaq (may be delayed). ") + "Research tool, not investment advice; no trades are placed without human approval._")
    text = "\n\n".join(parts)
    if llm is not None and getattr(llm, "available", False):
        try:
            return llm.complete("You are a concise portfolio-desk analyst. Rewrite the findings for a PM in <=140 words, keep every number "
                                "and the data-provenance and not-advice caveats, keep markdown.",
                                [{"role": "user", "content": f"Request: {prompt}\n\nFindings:\n{text}"}], 600)
        except Exception:  # noqa: BLE001
            pass
    return text
