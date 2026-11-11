"""Central configuration. Everything is driven by environment variables so the same
image runs on a laptop, in docker-compose and on AWS (ECS/Fargate)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "AVGO", "ADBE", "INTC", "QCOM", "NFLX", "CSCO", "INTU", "PANW",
]


def _load_dotenv() -> None:
    """Tiny .env loader (no dependency): KEY=VALUE lines from the repo root; real environment variables win."""
    f = Path(__file__).resolve().parents[1] / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("#") else ""
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("MERIDIAN_DATA_DIR", "./.meridian")))
    # market data: auto = Nasdaq with automatic fallback to the simulator
    provider: str = field(default_factory=lambda: _env("MERIDIAN_PROVIDER", "auto"))
    nasdaq_timeout_s: float = field(default_factory=lambda: float(_env("NASDAQ_TIMEOUT_S", "4")))
    # LLM (optional: the harness has a deterministic offline planner)
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: _env("MERIDIAN_MODEL", "claude-sonnet-5-5"))
    # sandbox
    sandbox_backend: str = field(default_factory=lambda: _env("SANDBOX_BACKEND", "local"))  # local|docker
    sandbox_image: str = field(default_factory=lambda: _env("SANDBOX_IMAGE", "meridian-sandbox:latest"))
    sandbox_timeout_s: float = field(default_factory=lambda: float(_env("SANDBOX_TIMEOUT_S", "25")))
    sandbox_mem_mb: int = field(default_factory=lambda: int(_env("SANDBOX_MEM_MB", "2048")))
    # harness budgets
    max_tool_calls: int = field(default_factory=lambda: int(_env("MAX_TOOL_CALLS", "80")))
    max_repair_attempts: int = field(default_factory=lambda: int(_env("MAX_REPAIR_ATTEMPTS", "3")))
    context_budget_tokens: int = field(default_factory=lambda: int(_env("CONTEXT_BUDGET_TOKENS", "6000")))
    # MCP transport between harness and MCP servers: inproc | stdio
    mcp_transport: str = field(default_factory=lambda: _env("MCP_TRANSPORT", "inproc"))
    # background jobs
    job_backend: str = field(default_factory=lambda: _env("MERIDIAN_JOBS", "thread"))  # thread|celery
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    universe: tuple = field(default_factory=lambda: tuple(UNIVERSE))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "meridian.db"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit.jsonl"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings() -> None:
    get_settings.cache_clear()
