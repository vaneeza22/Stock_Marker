"""LLM adapters. The harness works with or without a model: `NullLLM` makes the deterministic
template planner take over, so the whole product (and CI) runs offline."""
from __future__ import annotations

from typing import Dict, List, Protocol


class LLM(Protocol):
    available: bool

    def complete(self, system: str, messages: List[Dict[str, str]], max_tokens: int = 2500) -> str: ...


class NullLLM:
    available = False

    def complete(self, system, messages, max_tokens=2500) -> str:
        raise RuntimeError("no LLM configured")


class AnthropicLLM:
    """Direct Messages-API call over httpx (no SDK dependency)."""
    available = True

    def __init__(self, api_key: str, model: str, timeout_s: float = 60):
        import httpx
        self.model = model
        self._c = httpx.Client(timeout=timeout_s, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                                           "content-type": "application/json"})

    def complete(self, system: str, messages: List[Dict[str, str]], max_tokens: int = 2500) -> str:
        r = self._c.post("https://api.anthropic.com/v1/messages",
                         json={"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


class ScriptedLLM:
    """Test double: returns queued responses in order."""
    available = True

    def __init__(self, responses: List[str]):
        self.responses, self.calls = list(responses), []

    def complete(self, system, messages, max_tokens=2500) -> str:
        self.calls.append({"system": system, "messages": messages})
        if not self.responses:
            raise RuntimeError("ScriptedLLM exhausted")
        return self.responses.pop(0)


def build_llm(settings) -> LLM:
    if settings.anthropic_api_key:
        return AnthropicLLM(settings.anthropic_api_key, settings.model)
    return NullLLM()
