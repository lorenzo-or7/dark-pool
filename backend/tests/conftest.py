from __future__ import annotations

import gzip
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DEMO = {"Authorization": "Bearer demo-local"}


@pytest.fixture()
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DP_AUTH_MODE", "demo")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SEC_USER_AGENT", "")
    # Functional tests run many jobs back to back; the limits have their own tests.
    monkeypatch.setenv("DP_RATE_LIMIT_JOBS_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_WRITES_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "10000")
    _reset()
    yield tmp_path
    _reset()


def _reset() -> None:
    from app import auth, config, db, limits
    from app.services import jobs, providers
    config.get_settings.cache_clear()
    providers.reset()
    limits.windows.reset()
    auth.reset_public_cache()
    db.reset_engine()
    if jobs._pool is not None:
        jobs._pool.shutdown(wait=True)
        jobs._pool = None


@pytest.fixture()
def client(settings_env: Path) -> Iterator[TestClient]:
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def offline_yahoo(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network in tests: 5-minute requests get the skill's saved TSLA file."""
    from app.services import market_data as md

    with gzip.open(md.fixture_path(), "rt", encoding="utf-8") as fh:
        text = fh.read()

    def fake(symbol: str, rng: str, interval: str, use_cache: bool = True):  # noqa: ANN202
        if interval != "5m" or md.clean_symbol(symbol) != "TSLA":
            raise md.DataError("provider_unreachable", "offline test")
        return text, md.now(), False

    monkeypatch.setattr(md, "fetch_chart_raw", fake)


def wait_job(client: TestClient, job_id: str, headers: dict = DEMO, timeout: float = 120) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")
