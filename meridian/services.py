"""Process-wide service container (API process and each Celery worker build their own)."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from .config import Settings, get_settings
from .data.providers import build_provider
from .harness.audit import AuditLog
from .harness.core import Harness
from .harness.llm import LLM, build_llm
from .jobs.store import Store
from .mcp.client import McpRegistry, build_registry


@dataclass
class Services:
    settings: Settings
    store: Store
    audit: AuditLog
    registry: McpRegistry
    harness: Harness
    provider: object
    llm: LLM


_lock = threading.Lock()
_svc: Optional[Services] = None


def get_services() -> Services:
    global _svc
    with _lock:
        if _svc is None:
            s = get_settings()
            store, audit = Store(s.db_path), AuditLog(s.audit_path)
            registry = build_registry(s)
            llm = build_llm(s)
            _svc = Services(s, store, audit, registry, Harness(s, registry, audit, llm), build_provider(s), llm)
        return _svc


def reset_services() -> None:
    global _svc
    with _lock:
        if _svc is not None:
            _svc.registry.close()
        _svc = None
