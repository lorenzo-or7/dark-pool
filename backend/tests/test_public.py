"""Public shared lab (DP_AUTH_MODE=public) on the local SQLite database, plus the request
limits and the snapshot storage. The Postgres + RLS checks are in test_public_pg.py."""

from __future__ import annotations

import gzip
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import _reset, wait_job

REF_PLAN = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
            "entry_time": "10:15", "replays": 2000, "seed": 19}


def _demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    """An existing lab: the demo bootstrap creates a workspace with strategies and a journal."""
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setenv("DP_AUTH_MODE", "demo")
    _reset()
    from app.auth import DEMO_WORKSPACE_ID
    from app.services.seed import bootstrap_demo
    bootstrap_demo()
    return DEMO_WORKSPACE_ID


@pytest.fixture()
def public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, uuid.UUID]]:
    ws = _demo_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", str(ws))
    monkeypatch.setenv("DP_RATE_LIMIT_JOBS_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_WRITES_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "10000")
    # These tests exercise jobs with the offline Yahoo stub; the default policy (Yahoo off in
    # the public lab) has its own tests in test_policy.py.
    monkeypatch.setenv("DP_ALLOW_UNOFFICIAL_SOURCES", "true")
    _reset()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(ws)
    setup_public_lab(ws)  # idempotent
    from app.main import create_app
    with TestClient(create_app(), client=("198.51.100.7", 4000)) as c:
        yield c, ws
    _reset()


def test_public_lab_needs_no_login_and_ignores_client_identity(public) -> None:  # noqa: ANN001
    c, ws = public
    me = c.get("/api/me").json()
    assert me["mode"] == "public" and me["role"] == "public"
    assert me["display_name"] == "Laboratório compartilhado"
    assert "email" not in me and "id" not in me
    assert me["workspace"]["id"] == str(ws)
    forged = {"Authorization": "Bearer demo-local", "X-Workspace-Id": str(uuid.uuid4())}
    assert c.get("/api/me", headers=forged).json() == me
    assert c.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code == 200


def test_existing_data_is_kept_and_shared(public) -> None:  # noqa: ANN001
    c, _ = public
    names = [s["name"] for s in c.get("/api/strategies").json()]
    assert any("demonstração" in n for n in names), "the existing workspace's strategies are visible"
    journal = c.get("/api/journal").json()
    assert journal and all("author_email" not in e and "author_name" not in e for e in journal)


def test_workspace_response_has_no_accounts(public) -> None:  # noqa: ANN001
    c, _ = public
    w = c.get("/api/workspace").json()
    assert w["members"] == [] and w["shared"] is True
    assert set(w["workspace"]) == {"id", "name", "is_demo", "created_at"}
    body = c.get("/api/workspace").text + c.get("/api/me").text
    assert "@" not in body


def test_preferences_are_not_written_to_the_server(public) -> None:  # noqa: ANN001
    c, _ = public
    r = c.patch("/api/me", json={"display_name": "Lorenzo"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "preferences_in_browser"


def test_two_visitors_share_strategies_and_jobs(public) -> None:  # noqa: ANN001
    c, _ = public
    from app.main import app as _  # noqa: F401
    other = TestClient(c.app, client=("203.0.113.50", 5000))
    cfg = {"symbol": "AAPL", "rule": {"type": "breakout_20d"}, "exit": {"stop_type": "pct", "stop_value": 3}}
    sid = c.post("/api/strategies", json={"name": "Compartilhada", "config": cfg}).json()["id"]
    assert other.get(f"/api/strategies/{sid}").status_code == 200

    snap = [s for s in c.get("/api/snapshots?symbol=TSLA&interval=5m").json() if s["is_fixture"]][0]["id"]
    r = c.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap}).json()
    listed = other.get("/api/jobs").json()
    assert any(j["id"] == r["job"]["id"] and j["experiment_id"] == r["experiment_id"] for j in listed)
    done = wait_job(other, r["job"]["id"], headers={})
    assert done["status"] == "succeeded"
    finished = [j for j in other.get("/api/jobs").json() if j["id"] == r["job"]["id"]][0]
    assert finished["status"] == "succeeded" and finished["title"].startswith("Time Machine")
    assert other.get(f"/api/experiments/{r['experiment_id']}").json()["status"] == "succeeded"


def test_unconfigured_public_mode_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _demo_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    from app.main import create_app
    for value, msg in (("", "DP_PUBLIC_WORKSPACE_ID não está configurado"),
                       ("not-a-uuid", "não é um UUID válido"),
                       (str(uuid.uuid4()), "não foi preparado")):
        monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", value)
        _reset()
        with TestClient(create_app()) as c:
            r = c.get("/api/strategies")
            assert r.status_code == 503, value
            assert r.json()["detail"]["code"] == "public_lab_unconfigured"
            assert msg in r.json()["detail"]["message"]
            h = c.get("/api/health").json()
            assert h["status"] == "degraded" and h["public_lab"] == "unconfigured"
    _reset()


def test_restart_closes_jobs_left_running(public) -> None:  # noqa: ANN001
    c, ws = public
    from app.auth import public_lab_user
    from app.db import experiments, get_engine, jobs, now
    from app.services.jobs import mark_interrupted_on_start
    jid, eid = uuid.uuid4(), uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(jobs.insert().values(id=jid, workspace_id=ws, type="backtest.run", params={"experiment_id": str(eid)},
                                          dedupe_key="x" * 64, status="running", progress=40, stage="Rodando",
                                          created_at=now(), started_at=now()))
        conn.execute(experiments.insert().values(id=eid, workspace_id=ws, kind="backtest", title="Interrompido",
                                                 status="running", params={}, dataset="full", job_id=jid,
                                                 created_at=now(), updated_at=now()))
    assert mark_interrupted_on_start(public_lab_user()) == 1
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "failed" and "reiniciou" in j["error"]
    e = c.get(f"/api/experiments/{eid}").json()
    assert e["status"] == "failed" and "reiniciou" in e["error"]


def test_queue_full_is_refused_by_the_server(public, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, ws = public
    monkeypatch.setenv("DP_MAX_ACTIVE_JOBS", "1")
    from app import config
    config.get_settings.cache_clear()
    from app.db import get_engine, jobs, now
    with get_engine().begin() as conn:
        conn.execute(jobs.insert().values(id=uuid.uuid4(), workspace_id=ws, type="scan.universe", params={},
                                          dedupe_key="y" * 64, status="running", created_at=now(), started_at=now()))
    r = c.post("/api/timemachine", json=REF_PLAN)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "queue_full"
    assert r.headers.get("retry-after")


def test_duplicate_submission_returns_the_same_job(public) -> None:  # noqa: ANN001
    c, _ = public
    snap = [s for s in c.get("/api/snapshots?symbol=TSLA&interval=5m").json() if s["is_fixture"]][0]["id"]
    body = {**REF_PLAN, "snapshot_id": snap, "replays": 50000}
    a = c.post("/api/timemachine", json=body).json()
    b = TestClient(c.app, client=("203.0.113.77", 1)).post("/api/timemachine", json=body).json()
    assert a["job"]["id"] == b["job"]["id"] and b["created"] is False
    c.post(f"/api/jobs/{a['job']['id']}/cancel")
    wait_job(c, a["job"]["id"], headers={})


# ---------------------------------------------------------------- request limits

def test_rate_limits_answer_429(public, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _ = public
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "5")
    monkeypatch.setenv("DP_RATE_LIMIT_JOBS_PER_MIN", "2")
    from app import config, limits
    config.get_settings.cache_clear()
    limits.windows.reset()
    codes = [c.get("/api/strategies").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    other = TestClient(c.app, client=("192.0.2.1", 1))
    assert other.get("/api/strategies").status_code == 200, "limits are per client"
    assert c.get("/api/health").status_code == 200, "health is never limited"
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "1000")
    config.get_settings.cache_clear()
    limits.windows.reset()
    bad = {**REF_PLAN, "replays": 1}  # rejected by validation, but still counted as a job request
    codes = [c.post("/api/timemachine", json=bad).status_code for _ in range(3)]
    assert codes == [422, 422, 429]
    r = c.post("/api/timemachine", json=bad)
    assert r.json()["detail"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1


def test_body_and_upload_size_limits(public) -> None:  # noqa: ANN001
    c, _ = public
    big = {"title": "x", "body": "a" * 300_000, "entry_date": "2026-10-20"}
    r = c.post("/api/journal", json=big)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
    eid = c.post("/api/journal", json={"title": "anexo", "entry_date": "2026-10-20"}).json()["id"]
    png = b"\x89PNG" + b"0" * (5 * 1024 * 1024 + 10)
    r = c.post(f"/api/journal/{eid}/attachments", files={"file": ("a.png", png, "image/png")})
    assert r.status_code == 413


# ---------------------------------------------------------------- snapshots in private storage

class FakeStorage:
    """In-memory Supabase Storage: checks the server key and records object names."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    def _ok(self, headers: dict) -> bool:
        return headers.get("apikey") == "sb_secret_test" and "Authorization" not in headers

    def _name(self, url: str) -> str:
        return url.split("/storage/v1/object/", 1)[1].removeprefix("authenticated/")

    def post(self, url: str, content: bytes, headers: dict, timeout: float):  # noqa: ANN201
        self.calls.append(("post", self._name(url)))
        assert self._ok(headers)
        self.objects[self._name(url)] = content
        return _Resp(200, b"{}")

    def get(self, url: str, headers: dict, timeout: float):  # noqa: ANN201
        self.calls.append(("get", self._name(url)))
        assert self._ok(headers)
        data = self.objects.get(self._name(url))
        return _Resp(200, data) if data is not None else _Resp(400, b'{"error":"not_found"}')

    def delete(self, url: str, headers: dict, timeout: float):  # noqa: ANN201
        self.objects.pop(self._name(url), None)
        return _Resp(200, b"{}")


class _Resp:
    def __init__(self, status: int, content: bytes) -> None:
        self.status_code = status
        self.content = content


def test_snapshot_survives_a_wiped_disk(public, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    c, ws = public
    fake = FakeStorage()
    from app.services import storage
    monkeypatch.setattr(storage.httpx, "post", fake.post)
    monkeypatch.setattr(storage.httpx, "get", fake.get)
    monkeypatch.setattr(storage.httpx, "delete", fake.delete)
    monkeypatch.setenv("DP_STORAGE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")
    from app import config
    config.get_settings.cache_clear()

    from app.auth import public_lab_user
    from app.db import tx
    from app.services import market_data as md
    with gzip.open(md.fixture_path(), "rt", encoding="utf-8") as fh:
        text = fh.read().replace('"TSLA"', '"TSLA" ', 1)  # a payload that is not the bundled file
    u = public_lab_user()
    with tx(u.id, u.email) as conn:
        row = md.freeze_snapshot(conn, ws, u.id, text, "TSLA", "5m", "60d", "yahoo", md.now())
    key = f"{ws}/{row['sha256']}.json.gz"
    assert ("post", f"snapshots/{key}") in fake.calls, "stored under the workspace's prefix"

    for f in (config.get_settings().dp_data_dir / "snapshots").glob("*.json.gz"):
        f.unlink()  # the host's disk is gone after a restart
    sessions = c.get(f"/api/snapshots/{row['id']}/sessions")
    assert sessions.status_code == 200 and sessions.json()["sessions"]
    assert ("get", f"snapshots/{key}") in fake.calls
    assert md.sha256_text(md.read_snapshot_text(row["sha256"], ws)) == row["sha256"]

    fake.objects[f"snapshots/{key}"] = gzip.compress(b"tampered")
    for f in (config.get_settings().dp_data_dir / "snapshots").glob("*.json.gz"):
        f.unlink()
    r = c.get(f"/api/snapshots/{row['id']}/sessions")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "snapshot_corrupt"


def test_storage_keys_cannot_leave_the_workspace() -> None:
    from app.services import storage
    ws, other = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(storage.StorageError):
        storage.get("snapshots", f"{other}/x.json.gz", ws)
    with pytest.raises(storage.StorageError):
        storage.object_key(ws, "../", f"{other}")


def test_client_ip_ignores_spoofed_forwarded_for(public, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _ = public
    monkeypatch.setenv("DP_TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "3")
    from app import config, limits
    config.get_settings.cache_clear()
    limits.windows.reset()
    # The proxy appends the real address last; whatever the visitor wrote before it is ignored.
    codes = [c.get("/api/strategies", headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.200"}).status_code
             for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_one_visitor_cannot_hold_the_whole_queue(public, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, ws = public
    monkeypatch.setenv("DP_MAX_ACTIVE_JOBS_PER_CLIENT", "1")
    from app import config
    config.get_settings.cache_clear()
    snap = [s for s in c.get("/api/snapshots?symbol=TSLA&interval=5m").json() if s["is_fixture"]][0]["id"]
    first = c.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap, "replays": 50000, "seed": 1}).json()
    r = c.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap, "replays": 50000, "seed": 2})
    assert r.status_code == 429 and "Você já tem" in r.json()["detail"]["message"]
    other = TestClient(c.app, client=("203.0.113.90", 1))
    second = other.post("/api/timemachine", json={**REF_PLAN, "snapshot_id": snap, "replays": 50000, "seed": 3})
    assert second.status_code == 202, "another visitor still gets a slot"
    for j in (first["job"]["id"], second.json()["job"]["id"]):
        c.post(f"/api/jobs/{j}/cancel")
        wait_job(c, j, headers={})


def test_heavy_reads_and_ipv6_buckets(public, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _ = public
    monkeypatch.setenv("DP_RATE_LIMIT_HEAVY_PER_MIN", "2")
    from app import config, limits
    config.get_settings.cache_clear()
    limits.windows.reset()
    codes = [c.get("/api/quotes?symbols=BAD$").status_code for _ in range(3)]
    assert codes[2] == 429
    assert c.get("/api/strategies").status_code == 200, "ordinary reads are not affected"
    assert limits._bucket("2001:db8:1:2:aaaa::1") == limits._bucket("2001:db8:1:2:bbbb::9")
    assert limits._bucket("2001:db8:1:3::1") != limits._bucket("2001:db8:1:2::1")
    assert limits._bucket("::ffff:198.51.100.4") == "198.51.100.4"


def test_public_rows_carry_no_author_ids(public) -> None:  # noqa: ANN001
    c, _ = public
    for path in ("/api/strategies", "/api/journal", "/api/watchlists", "/api/experiments", "/api/snapshots"):
        body = c.get(path).text
        for key in ("created_by", "updated_by", "added_by", "actor_id"):
            assert key not in body, (path, key)


def test_a_job_closed_as_interrupted_is_not_reopened(public) -> None:  # noqa: ANN001
    c, ws = public
    from app.auth import public_lab_user
    from app.db import get_engine, jobs, now
    from app.services import jobs as jobsvc
    jid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(jobs.insert().values(id=jid, workspace_id=ws, type="scan.universe", params={},
                                          dedupe_key="z" * 64, status="failed", stage="Interrompido",
                                          error=jobsvc.INTERRUPTED_RESTART, created_at=now(), finished_at=now()))
    jobsvc._run(jid, public_lab_user(), "scan.universe", {})  # a late worker for that job
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "failed" and j["error"] == jobsvc.INTERRUPTED_RESTART
