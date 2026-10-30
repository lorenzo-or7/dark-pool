"""Public shared lab on PostgreSQL with the real migrations and RLS policies.

Needs a local PostgreSQL. Set DP_TEST_PG_URL to a superuser connection on a throwaway server,
for example postgresql://postgres@127.0.0.1:5433/postgres. The test creates and drops its own
database and applies supabase/tests/supabase_stub.sql (a stand-in for Supabase's auth and
storage schemas) followed by every file in supabase/migrations. Skipped when not set.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from .conftest import _reset, wait_job

PG = os.environ.get("DP_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG, reason="DP_TEST_PG_URL not set (local PostgreSQL needed)")
ROOT = Path(__file__).resolve().parents[2]

LORENZO, LIPE, OUTSIDER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
LAB_WS, OTHER_WS = uuid.uuid4(), uuid.uuid4()


def _url(db: str) -> str:
    base = PG.replace("postgresql://", "postgresql+psycopg://", 1)
    return base.rsplit("/", 1)[0] + "/" + db


def _run_sql(conn, path: Path) -> None:  # noqa: ANN001
    # Straight to psycopg without parameters, so '%I' in format() calls is left alone.
    conn.connection.driver_connection.execute(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pgdb() -> Iterator[dict]:
    name = "dp_test_" + uuid.uuid4().hex[:8]
    admin = create_engine(_url(PG.rsplit("/", 1)[1]), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'create database "{name}"')
    eng = create_engine(_url(name))
    with eng.begin() as conn:
        _run_sql(conn, ROOT / "supabase" / "tests" / "supabase_stub.sql")
        for m in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
            _run_sql(conn, m)
        ids = {}
        # Two people in the existing DARK POOL workspace, and an unrelated workspace.
        for uid, email in ((LORENZO, "lorenzo@example.com"), (LIPE, "lipe@example.com"),
                           (OUTSIDER, "outro@example.com")):
            conn.execute(text("insert into auth.users (id, aud, role, email, encrypted_password, raw_app_meta_data,"
                              " created_at, updated_at) values (:id,'authenticated','authenticated',:e,'x',"
                              " '{\"provider\":\"email\"}', now(), now())"), {"id": uid, "e": email})
        conn.execute(text("insert into public.workspaces (id, name, settings) values (:a,'DARK POOL','{\"k\":\"v\"}'),"
                          " (:b,'Outro laboratório','{}')"), {"a": LAB_WS, "b": OTHER_WS})
        conn.execute(text("insert into public.workspace_members (workspace_id, user_id, role) values"
                          " (:a,:l,'owner'), (:a,:p,'member'), (:b,:o,'owner')"),
                     {"a": LAB_WS, "b": OTHER_WS, "l": LORENZO, "p": LIPE, "o": OUTSIDER})
        cfg = '{"symbol":"AAPL","rule":{"type":"breakout_20d","params":{"lookback":20}},"exit":{"stop_type":"pct","stop_value":3,"target_r":2,"max_hold_bars":10,"flat_by":"15:55"},"filters":{"min_price":5,"min_avg_volume":0},"risk":{"account_size":10000,"max_loss_per_trade":100,"max_position_pct":50,"daily_loss_limit":300,"max_trades_per_day":3,"min_reward_risk":1}}'
        for key, ws, author, nm in (("lab", LAB_WS, LORENZO, "Estratégia existente do laboratório"),
                                    ("other", OTHER_WS, OUTSIDER, "Estratégia de outro workspace")):
            sid, eid, jid, aid, snap = (uuid.uuid4() for _ in range(5))
            conn.execute(text("insert into public.strategies (id, workspace_id, name, symbol, rule_type, created_by,"
                              " updated_by) values (:s,:w,:n,'AAPL','breakout_20d',:u,:u)"),
                         {"s": sid, "w": ws, "n": nm, "u": author})
            conn.execute(text("insert into public.strategy_versions (workspace_id, strategy_id, version, config,"
                              " created_by) values (:w,:s,1,cast(:c as jsonb),:u)"),
                         {"w": ws, "s": sid, "c": cfg, "u": author})
            conn.execute(text("insert into public.experiments (id, workspace_id, strategy_id, kind, title, status,"
                              " params, created_by) values (:e,:w,:s,'backtest','Resultado existente','succeeded',"
                              " '{}', :u)"), {"e": eid, "w": ws, "s": sid, "u": author})
            conn.execute(text("insert into public.journal_entries (id, workspace_id, title, entry_date, created_by,"
                              " updated_by) values (:j,:w,'Nota existente','2026-10-20',:u,:u)"),
                         {"j": jid, "w": ws, "u": author})
            conn.execute(text("insert into public.attachments (id, workspace_id, journal_entry_id, filename,"
                              " content_type, size, storage, path, created_by) values (:a,:w,:j,'a.png','image/png',"
                              " 10,'local','x.png',:u)"), {"a": aid, "w": ws, "j": jid, "u": author})
            conn.execute(text("insert into public.data_snapshots (id, workspace_id, symbol, interval, range, source,"
                              " sha256, storage_path, bars, fetched_at, created_by) values (:i,:w,'TSLA','5m','60d',"
                              " 'yahoo', :h, 'x', 1, now(), :u)"),
                         {"i": snap, "w": ws, "h": uuid.uuid4().hex + uuid.uuid4().hex, "u": author})
            ids[key] = {"strategy": sid, "experiment": eid, "journal": jid, "attachment": aid, "snapshot": snap}
    yield {"name": name, "url": _url(name), "ids": ids, "engine": eng}
    eng.dispose()
    with admin.connect() as c:
        c.exec_driver_sql(f'drop database "{name}" with (force)')
    admin.dispose()


@pytest.fixture()
def lab(pgdb: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", pgdb["url"].replace("+psycopg", ""))
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", str(LAB_WS))
    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setenv("DP_RATE_LIMIT_JOBS_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_WRITES_PER_MIN", "1000")
    monkeypatch.setenv("DP_RATE_LIMIT_PER_MIN", "10000")
    monkeypatch.setenv("DP_ALLOW_UNOFFICIAL_SOURCES", "true")  # job tests use the offline Yahoo stub
    _reset()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(LAB_WS)
    setup_public_lab(LAB_WS)  # idempotent
    from app.main import create_app
    with TestClient(create_app(), client=("198.51.100.9", 1)) as c:
        yield c
    _reset()


def _as(conn, uid: uuid.UUID | None, role: str = "authenticated") -> None:  # noqa: ANN001
    if uid:
        conn.execute(text("select set_config('request.jwt.claims', :c, true)"),
                     {"c": '{"sub":"%s","role":"%s"}' % (uid, role)})
    conn.execute(text(f"set local role {role}"))


def _ident() -> uuid.UUID:
    from app.auth import public_identity_id
    return public_identity_id(LAB_WS)


def test_setup_is_idempotent_and_keeps_existing_data(lab: TestClient, pgdb: dict) -> None:
    with pgdb["engine"].begin() as conn:
        u = conn.execute(text("select encrypted_password, banned_until, raw_app_meta_data, email from auth.users"
                              " where id = :i"), {"i": _ident()}).mappings().one()
        assert u["encrypted_password"] == ""
        assert u["banned_until"].year >= 2100
        assert u["raw_app_meta_data"]["dp_technical"] is True
        mem = conn.execute(text("select workspace_id, role from public.workspace_members where user_id = :i"),
                           {"i": _ident()}).all()
        assert mem == [(LAB_WS, "member")]
        assert conn.execute(text("select email from public.profiles where id = :i"), {"i": _ident()}).scalar() is None
        assert conn.execute(text("select count(*) from public.workspace_members where workspace_id = :w"),
                            {"w": LAB_WS}).scalar() == 3
    names = [s["name"] for s in lab.get("/api/strategies").json()]
    assert "Estratégia existente do laboratório" in names
    assert "Estratégia de outro workspace" not in names
    assert any(e["title"] == "Resultado existente" for e in lab.get("/api/experiments").json())


def test_setup_refuses_unknown_workspace_and_personal_ids(lab: TestClient) -> None:
    from app.services.public_lab import setup_public_lab
    with pytest.raises(DBAPIError, match="não existe"):
        setup_public_lab(uuid.uuid4())
    with pytest.raises(DBAPIError, match="conta pessoal"):
        setup_public_lab(LAB_WS, LORENZO)
    with pytest.raises(DBAPIError, match="outro workspace"):
        setup_public_lab(OTHER_WS, _ident())


def test_public_responses_carry_no_personal_data(lab: TestClient) -> None:
    for path in ("/api/me", "/api/workspace", "/api/journal", "/api/strategies", "/api/dashboard", "/api/jobs"):
        body = lab.get(path).text
        assert "@example.com" not in body and "lorenzo" not in body.lower() and "lipe" not in body.lower(), path
    ws = lab.get("/api/workspace").json()
    assert ws["members"] == [] and "settings" not in ws["workspace"]


def test_other_workspace_records_are_unreachable_by_id(lab: TestClient, pgdb: dict) -> None:
    o = pgdb["ids"]["other"]
    for path in (f"/api/strategies/{o['strategy']}", f"/api/experiments/{o['experiment']}",
                 f"/api/experiments/{o['experiment']}/export", f"/api/attachments/{o['attachment']}",
                 f"/api/snapshots/{o['snapshot']}/sessions", f"/api/analytics?experiment_id={o['experiment']}"):
        r = lab.get(path)
        assert r.status_code in (404, 200), path
        if r.status_code == 200:  # analytics answers with an empty selection
            assert r.json()["selected"] is None and r.json()["summary"]["trades"] == 0, path
    assert lab.patch(f"/api/strategies/{o['strategy']}", json={"name": "hack"}).status_code == 404
    assert lab.delete(f"/api/strategies/{o['strategy']}").status_code == 404
    assert lab.post(f"/api/strategies/{o['strategy']}/duplicate").status_code == 404
    assert lab.delete(f"/api/experiments/{o['experiment']}").status_code == 400
    assert lab.put(f"/api/journal/{o['journal']}", json={"title": "x", "entry_date": "2026-10-20"}).status_code == 404
    assert lab.delete(f"/api/journal/{o['journal']}").status_code == 404
    assert lab.delete(f"/api/attachments/{o['attachment']}").status_code == 404
    assert lab.post("/api/journal", json={"title": "x", "entry_date": "2026-10-20",
                                          "strategy_id": str(o["strategy"])}).status_code == 400
    assert lab.get(f"/api/analytics/compare?ids={o['experiment']}").json()["items"] == []
    assert lab.post("/api/backtests", json={"strategy_id": str(o["strategy"])}).status_code == 404
    with pgdb["engine"].begin() as conn:
        assert conn.execute(text("select name from public.strategies where id = :s"),
                            {"s": o["strategy"]}).scalar() == "Estratégia de outro workspace"


def test_rls_scopes_the_lab_identity(lab: TestClient, pgdb: dict) -> None:
    eng = pgdb["engine"]
    with eng.begin() as conn:
        _as(conn, _ident())
        assert conn.execute(text("select count(*) from public.strategies where workspace_id = :w"),
                            {"w": OTHER_WS}).scalar() == 0
        assert [r[0] for r in conn.execute(text("select id from public.profiles"))] == [_ident()]
        assert [r[0] for r in conn.execute(text("select user_id from public.workspace_members"))] == [_ident()]
        assert conn.execute(text("update public.profiles set display_name = 'x' where id = :i"),
                            {"i": LORENZO}).rowcount == 0
        assert conn.execute(text("update public.profiles set display_name = 'x' where id = :i"),
                            {"i": _ident()}).rowcount == 0
    for sql, params in (
        ("insert into public.workspace_members (workspace_id, user_id, role) values (:w, :u, 'owner')",
         {"w": LAB_WS, "u": _ident()}),
        ("insert into public.strategies (workspace_id, name, rule_type) values (:w, 'intrusa', 'orb')", {"w": OTHER_WS}),
        ("insert into public.strategies (workspace_id, name, rule_type, created_by) values (:w, 'falsa', 'orb', :u)",
         {"w": LAB_WS, "u": LORENZO}),
        ("insert into storage.objects (bucket_id, name) values ('snapshots', :n)", {"n": f"{OTHER_WS}/x.json.gz"}),
        ("delete from public.audit_events", {}),
    ):
        with pytest.raises(DBAPIError), eng.begin() as conn:
            _as(conn, _ident())
            conn.execute(text(sql), params)
    with eng.begin() as conn:  # its own folder is allowed
        _as(conn, _ident())
        conn.execute(text("insert into storage.objects (bucket_id, name) values ('snapshots', :n)"),
                     {"n": f"{LAB_WS}/ok.json.gz"})


def test_people_keep_their_access(lab: TestClient, pgdb: dict) -> None:
    with pgdb["engine"].begin() as conn:
        _as(conn, LORENZO)
        members = {r[0] for r in conn.execute(text("select user_id from public.workspace_members"))}
        assert {LORENZO, LIPE, _ident()} <= members
        assert conn.execute(text("select count(*) from public.profiles")).scalar() >= 2


def test_anon_reads_nothing(lab: TestClient, pgdb: dict) -> None:
    for table in ("strategies", "experiments", "journal_entries", "profiles", "workspaces", "jobs", "attachments",
                  "data_snapshots", "audit_events"):
        with pytest.raises(DBAPIError, match="permission denied"), pgdb["engine"].begin() as conn:
            _as(conn, None, "anon")
            conn.execute(text(f"select count(*) from public.{table}"))
    with pgdb["engine"].begin() as conn:
        _as(conn, None, "anon")
        assert conn.execute(text("select count(*) from storage.objects")).scalar() == 0
        conn.execute(text("reset role"))
        assert conn.execute(text("select bool_or(public) from storage.buckets")).scalar() is False
    for fn in ("public.dp_setup_public_lab(gen_random_uuid(), gen_random_uuid())",):
        for role in ("anon", "authenticated"):
            with pytest.raises(DBAPIError, match="permission denied"), pgdb["engine"].begin() as conn:
                _as(conn, _ident(), role)
                conn.execute(text(f"select * from {fn}"))


def test_jobs_run_under_rls_and_authors_are_stamped(lab: TestClient, pgdb: dict) -> None:
    cfg = {"symbol": "TSLA", "rule": {"type": "orb"}, "exit": {"stop_type": "or_mid", "target_r": 1}}
    sid = lab.post("/api/strategies", json={"name": "Pública ORB", "config": cfg}).json()["id"]
    snap = lab.post("/api/snapshots/fixture").json()["id"]
    r = lab.post("/api/backtests", json={"strategy_id": sid, "snapshot_id": snap}).json()
    other_browser = TestClient(lab.app, client=("203.0.113.5", 2))
    assert any(j["id"] == r["job"]["id"] for j in other_browser.get("/api/jobs").json())
    done = wait_job(other_browser, r["job"]["id"], headers={})
    assert done["status"] == "succeeded", done
    with pgdb["engine"].begin() as conn:
        by = conn.execute(text("select created_by from public.strategies where id = :s"), {"s": sid}).scalar()
        assert by == _ident()
        actor = conn.execute(text("select actor_id from public.audit_events where entity_id = :s"),
                             {"s": sid}).scalar()
        assert actor == _ident()
    assert lab.get(f"/api/analytics?experiment_id={r['experiment_id']}").json()["summary"]["trades"] > 0


def test_time_machine_refuses_another_workspaces_strategy(lab: TestClient, pgdb: dict) -> None:
    o = pgdb["ids"]["other"]
    plan = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
            "entry_time": "10:15", "replays": 500, "seed": 1, "strategy_id": str(o["strategy"])}
    assert lab.post("/api/timemachine", json=plan).status_code == 404
    plan["strategy_id"] = str(uuid.uuid4())
    assert lab.post("/api/timemachine", json=plan).status_code == 404
