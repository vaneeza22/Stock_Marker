import pytest

from meridian.config import reset_settings
from meridian.services import reset_services


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MERIDIAN_PROVIDER", "synthetic")
    monkeypatch.setenv("MERIDIAN_JOBS", "thread")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings(); reset_services()
    yield tmp_path
    reset_services(); reset_settings()


@pytest.fixture()
def svc(env):
    from meridian.services import get_services
    return get_services()
