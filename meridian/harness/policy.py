"""Policy engine: roles, tool allow-lists, data scope, per-run budgets, and untrusted-output quarantine."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..mcp.client import ToolInfo

ROLES: Dict[str, Dict[str, Any]] = {
    # viewer: universe symbols only, read-only tools, small budget
    "viewer": {"propose": False, "scope": "universe", "max_calls": 30},
    "analyst": {"propose": False, "scope": "any", "max_calls": 80},
    # pm: may *request* paper trades; a separate human approval still gates execution
    "pm": {"propose": True, "scope": "any", "max_calls": 120},
}
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
INJECTION_RE = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard .{0,30}instructions|"
    r"you are now|system prompt|reveal .{0,20}(key|secret|prompt)|<\s*/?\s*(tool|system|assistant)\b|"
    r"execute the following|call the tool)", re.I)


@dataclass
class Decision:
    effect: str  # allow | deny | needs_approval
    reason: str
    rule: str

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"


@dataclass
class Usage:
    tool_calls: int = 0
    sandbox_runs: int = 0
    denied: int = 0
    injection_hits: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, field_: str, n: int = 1) -> int:
        with self._lock:
            setattr(self, field_, getattr(self, field_) + n)
            return getattr(self, field_)


class PolicyEngine:
    def __init__(self, universe, max_prompt_chars: int = 2000):
        self.universe = set(universe)
        self.max_prompt_chars = max_prompt_chars

    def check_request(self, prompt: str, role: str) -> Decision:
        if role not in ROLES:
            return Decision("deny", f"unknown role '{role}'", "R-ROLE")
        if not prompt.strip():
            return Decision("deny", "empty request", "R-EMPTY")
        if len(prompt) > self.max_prompt_chars:
            return Decision("deny", f"request exceeds {self.max_prompt_chars} chars", "R-SIZE")
        return Decision("allow", f"role={role}", "R-OK")

    def check_tool(self, role: str, tool: ToolInfo, args: Dict[str, Any], usage: Usage, max_calls: int) -> Decision:
        cfg = ROLES[role]
        if usage.tool_calls >= min(max_calls, cfg["max_calls"]):
            return Decision("deny", "tool-call budget exhausted for this run", "T-BUDGET")
        if tool.sensitivity == "high" or not tool.read_only:
            if not cfg["propose"]:
                return Decision("deny", f"role '{role}' may not use {tool.full}", "T-ROLE")
            return Decision("needs_approval", f"{tool.full} only creates a pending request; human approval required", "T-HITL")
        syms = [args.get("symbol")] if args.get("symbol") else list(args.get("symbols") or [])
        for s in syms:
            if not isinstance(s, str) or not SYMBOL_RE.match(s.upper()):
                return Decision("deny", f"invalid ticker {s!r}", "D-SYMBOL")
            if cfg["scope"] == "universe" and s.upper() not in self.universe:
                return Decision("deny", f"{s} is outside the permitted data scope for role '{role}'", "D-SCOPE")
        return Decision("allow", "registered read-only tool within scope", "T-OK")


def quarantine(data: Any, hits: Optional[List[str]] = None) -> Any:
    """Tool output is DATA. Strip strings that read like instructions before anything downstream sees them."""
    hits = hits if hits is not None else []
    if isinstance(data, str):
        if INJECTION_RE.search(data):
            hits.append(data[:80])
            return "[redacted: suspected instruction in tool output]"
        return data
    if isinstance(data, list):
        return [quarantine(x, hits) for x in data]
    if isinstance(data, dict):
        return {k: quarantine(v, hits) for k, v in data.items()}
    return data
