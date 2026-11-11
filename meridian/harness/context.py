"""Context management.

The harness treats the model's context window as a scarce, budgeted resource:

 * pinned items (system rules, user constraints) are never evicted
 * oversized items are OFFLOADED to a ref store and replaced by a compact digest + `ref://` handle
 * when over budget, the oldest turns are COMPACTED into a rolling summary (extractive by default,
   LLM-assisted when a summarizer is supplied)
 * programmatic tool calling keeps raw tool output out of the window entirely; `stats()` reports the
   tokens saved vs. a naive "paste every tool result into the prompt" loop.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
NUM_RE = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*%?")


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Item:
    id: str
    kind: str            # system | pin | user | assistant | digest | summary
    text: str
    priority: int = 5    # 1 (drop first) .. 9
    pinned: bool = False
    ref: Optional[str] = None
    ts: float = field(default_factory=time.time)

    @property
    def tokens(self) -> int:
        return est_tokens(self.text)


def extractive_summary(items: List[Item], max_chars: int = 600) -> str:
    """Keeps what matters to a PM: tickers, the numbers attached to them, and each turn's first sentence."""
    lines, tickers = [], set()
    for it in items:
        first = re.split(r"(?<=[.!?])\s", it.text.strip(), maxsplit=1)[0][:140]
        lines.append(f"{it.kind[:1].upper()}: {first}")
        tickers |= {t for t in TICKER_RE.findall(it.text) if t not in {"THE", "AND", "FOR", "RSI", "MACD", "SMA", "PTC", "MCP"}}
    s = " | ".join(lines)
    s = (s[:max_chars] + "…") if len(s) > max_chars else s
    return f"{s} [tickers: {', '.join(sorted(tickers)[:12])}]" if tickers else s


class ContextManager:
    def __init__(self, budget_tokens: int = 6000, summarizer: Optional[Callable[[List[Item]], str]] = None,
                 high_water: float = 0.85, low_water: float = 0.65, offload_over: int = 350):
        self.budget, self.high, self.low, self.offload_over = budget_tokens, high_water, low_water, offload_over
        self.summarizer = summarizer or extractive_summary
        self.items: List[Item] = []
        self.refs: Dict[str, str] = {}
        self.compactions: List[Dict[str, Any]] = []
        self.naive_tokens = 0       # what a naive tool-calling loop would have pasted into the prompt
        self.offloaded_tokens = 0

    # ---- mutation ------------------------------------------------------------------------
    def add(self, kind: str, text: str, priority: int = 5, pinned: bool = False) -> Item:
        it = Item("c_" + uuid.uuid4().hex[:6], kind, text, priority, pinned)
        self.items.append(it)
        self.compact()
        return it

    def note_naive(self, raw_tool_bytes: int) -> None:
        self.naive_tokens += raw_tool_bytes // 4

    def offload(self, text: str) -> str:
        ref = "ref://ctx/" + uuid.uuid4().hex[:8]
        self.refs[ref] = text
        return ref

    def recall(self, ref: str) -> Optional[str]:
        return self.refs.get(ref)

    # ---- accounting ----------------------------------------------------------------------
    @property
    def used(self) -> int:
        return sum(i.tokens for i in self.items)

    def stats(self) -> Dict[str, Any]:
        by: Dict[str, int] = {}
        for i in self.items:
            by[i.kind] = by.get(i.kind, 0) + i.tokens
        return {"budget": self.budget, "used": self.used, "pct": round(100 * self.used / self.budget, 1),
                "by_kind": by, "items": len(self.items), "pinned": sum(i.pinned for i in self.items),
                "compactions": len(self.compactions), "offloaded_refs": len(self.refs),
                "offloaded_tokens": self.offloaded_tokens, "naive_tokens": self.naive_tokens,
                "saved_tokens": max(0, self.naive_tokens + self.offloaded_tokens - self.used) if self.naive_tokens else self.offloaded_tokens,
                "last_compaction": self.compactions[-1] if self.compactions else None}

    # ---- compaction ----------------------------------------------------------------------
    def compact(self) -> None:
        if self.used <= self.budget * self.high:
            return
        before = self.used
        actions: List[str] = []
        # 1) offload big, unpinned items -> digest + handle
        for it in sorted([i for i in self.items if not i.pinned and i.tokens > self.offload_over],
                         key=lambda i: -i.tokens):
            if self.used <= self.budget * self.low:
                break
            ref = self.offload(it.text)
            keep = it.text[: self.offload_over * 2]
            self.offloaded_tokens += it.tokens - est_tokens(keep)
            it.text = f"{keep}… [truncated; full text at {ref}]"
            it.ref = ref
            actions.append(f"offload:{it.kind}")
        # 2) fold the oldest turns into one rolling summary
        while self.used > self.budget * self.low:
            foldable = [i for i in self.items if not i.pinned and i.kind in ("user", "assistant", "digest", "summary")]
            if len(foldable) <= 2:   # always keep the latest exchange verbatim
                break
            take = foldable[: max(2, len(foldable) // 2)]
            merged = Item("c_" + uuid.uuid4().hex[:6], "summary", self.summarizer(take), priority=6)
            idx = self.items.index(take[0])
            self.items = [i for i in self.items if i not in take]
            self.items.insert(min(idx, len(self.items)), merged)
            actions.append(f"summarize:{len(take)}")
        # 3) last resort: drop lowest-priority unpinned items (never the newest two)
        protected = set(id(i) for i in self.items[-2:])
        for it in sorted([i for i in self.items if not i.pinned and id(i) not in protected], key=lambda i: (i.priority, i.ts)):
            if self.used <= self.budget:
                break
            self.items.remove(it)
            actions.append(f"drop:{it.kind}")
        self.compactions.append({"before": before, "after": self.used, "actions": actions, "ts": time.time()})

    # ---- rendering -----------------------------------------------------------------------
    def render(self) -> Dict[str, Any]:
        system = "\n\n".join(i.text for i in self.items if i.kind in ("system", "pin"))
        msgs: List[Dict[str, str]] = []
        for i in self.items:
            if i.kind in ("system", "pin"):
                continue
            role = "assistant" if i.kind == "assistant" else "user"
            text = i.text if i.kind in ("user", "assistant") else f"[{i.kind}] {i.text}"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if msgs and msgs[0]["role"] != "user":
            msgs.insert(0, {"role": "user", "content": "(conversation start)"})
        return {"system": system, "messages": msgs}

    # ---- persistence (sessions survive across Celery workers) --------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {"budget": self.budget, "items": [asdict(i) for i in self.items], "refs": self.refs,
                "compactions": self.compactions, "naive_tokens": self.naive_tokens,
                "offloaded_tokens": self.offloaded_tokens}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], **kw) -> "ContextManager":
        cm = cls(d.get("budget", 6000), **kw)
        cm.items = [Item(**i) for i in d.get("items", [])]
        cm.refs, cm.compactions = d.get("refs", {}), d.get("compactions", [])
        cm.naive_tokens, cm.offloaded_tokens = d.get("naive_tokens", 0), d.get("offloaded_tokens", 0)
        return cm
