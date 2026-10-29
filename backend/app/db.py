"""Database tables (SQLAlchemy Core) and the per-request transaction.

The Supabase migrations in supabase/migrations are the source of truth for
Postgres. These definitions mirror them so the same queries run on the local
SQLite demo database. On Postgres every transaction runs as the `authenticated`
role with the caller's JWT claims, so the RLS policies apply to the backend too.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Connection,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .config import get_settings

metadata = MetaData()
Json = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def _ts(name: str) -> Column:
    return Column(name, DateTime(timezone=True), nullable=False, default=now)


def _ws() -> Column:
    return Column("workspace_id", Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)


profiles = Table(
    "profiles", metadata,
    Column("id", Uuid, primary_key=True),
    Column("email", String(320)),
    Column("display_name", String(80)),
    Column("preferences", Json, nullable=False, default=dict),
    _ts("created_at"), _ts("updated_at"),
)

workspaces = Table(
    "workspaces", metadata,
    Column("id", Uuid, primary_key=True, default=new_id),
    Column("name", String(120), nullable=False),
    Column("is_demo", Boolean, nullable=False, default=False),
    Column("settings", Json, nullable=False, default=dict),
    _ts("created_at"), _ts("updated_at"),
)

workspace_members = Table(
    "workspace_members", metadata,
    Column("workspace_id", Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(16), nullable=False, default="member"),
    _ts("created_at"),
)

watchlists = Table(
    "watchlists", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("name", String(80), nullable=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    Column("updated_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"), _ts("updated_at"),
)

watchlist_assets = Table(
    "watchlist_assets", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("watchlist_id", Uuid, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False),
    Column("symbol", String(12), nullable=False),
    Column("note", String(280)),
    Column("added_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
    UniqueConstraint("watchlist_id", "symbol"),
)

strategies = Table(
    "strategies", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("name", String(120), nullable=False),
    Column("description", Text),
    Column("symbol", String(12)),
    Column("rule_type", String(32), nullable=False),
    Column("current_version", Integer, nullable=False, default=1),
    Column("is_demo", Boolean, nullable=False, default=False),
    Column("archived", Boolean, nullable=False, default=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    Column("updated_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"), _ts("updated_at"),
)

strategy_versions = Table(
    "strategy_versions", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("strategy_id", Uuid, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("config", Json, nullable=False),
    Column("note", String(280)),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
    UniqueConstraint("strategy_id", "version"),
)

data_snapshots = Table(
    "data_snapshots", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("symbol", String(12), nullable=False),
    Column("interval", String(8), nullable=False),
    Column("range", String(8), nullable=False),
    Column("source", String(40), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("storage_path", String(400), nullable=False),
    Column("bars", Integer, nullable=False),
    Column("first_bar", DateTime(timezone=True)),
    Column("last_bar", DateTime(timezone=True)),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("is_fixture", Boolean, nullable=False, default=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
    UniqueConstraint("workspace_id", "sha256"),
)

jobs = Table(
    "jobs", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("type", String(40), nullable=False),
    Column("params", Json, nullable=False),
    Column("dedupe_key", String(64), nullable=False, index=True),
    Column("status", String(16), nullable=False, default="queued"),
    Column("progress", Integer, nullable=False, default=0),
    Column("stage", String(200)),
    Column("result", Json),
    Column("error", Text),
    Column("cancel_requested", Boolean, nullable=False, default=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)

experiments = Table(
    "experiments", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("strategy_id", Uuid, ForeignKey("strategies.id", ondelete="SET NULL")),
    Column("strategy_version", Integer),
    Column("kind", String(16), nullable=False),  # backtest | monte_carlo
    Column("title", String(160), nullable=False),
    Column("status", String(16), nullable=False, default="queued"),
    Column("params", Json, nullable=False),
    Column("data_snapshot_id", Uuid, ForeignKey("data_snapshots.id", ondelete="SET NULL")),
    Column("dataset", String(16), nullable=False, default="full"),  # development | out_of_sample | full
    Column("results", Json),
    Column("error", Text),
    Column("job_id", Uuid, ForeignKey("jobs.id", ondelete="SET NULL")),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"), _ts("updated_at"),
)

simulation_runs = Table(
    "simulation_runs", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("experiment_id", Uuid, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
    Column("symbol", String(12), nullable=False),
    Column("plan", Json, nullable=False),
    Column("seed", Integer, nullable=False),
    Column("replays", Integer, nullable=False),
    Column("algorithm_version", String(80), nullable=False),
    Column("data_source", String(40), nullable=False),
    Column("data_snapshot_id", Uuid, ForeignKey("data_snapshots.id", ondelete="SET NULL")),
    Column("snapshot_sha256", String(64), nullable=False),
    Column("pool_from", String(10)),
    Column("pool_to", String(10)),
    Column("pool_sessions", Integer),
    Column("results", Json, nullable=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
)

simulated_trades = Table(
    "simulated_trades", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("experiment_id", Uuid, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("source", String(24), nullable=False),  # backtest | timemachine_history | paper
    Column("dataset", String(16), nullable=False, default="full"),
    Column("symbol", String(12), nullable=False),
    Column("entry_date", String(10), nullable=False),
    Column("entry_time", String(10)),
    Column("entry", Float, nullable=False),
    Column("stop", Float, nullable=False),
    Column("target", Float),
    Column("exit_price", Float),
    Column("exit_date", String(10)),
    Column("outcome", String(12), nullable=False),  # target | stop | close | time
    Column("r_multiple", Float, nullable=False),
    _ts("created_at"),
)

scan_runs = Table(
    "scan_runs", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("mode", String(16), nullable=False),
    Column("params", Json, nullable=False),
    Column("status", String(16), nullable=False, default="queued"),
    Column("result", Json),
    Column("error", Text),
    Column("job_id", Uuid, ForeignKey("jobs.id", ondelete="SET NULL")),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
)

journal_entries = Table(
    "journal_entries", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("title", String(160), nullable=False),
    Column("body", Text, nullable=False, default=""),
    Column("kind", String(20), nullable=False, default="note"),
    Column("symbol", String(12)),
    Column("strategy_id", Uuid, ForeignKey("strategies.id", ondelete="SET NULL")),
    Column("experiment_id", Uuid, ForeignKey("experiments.id", ondelete="SET NULL")),
    Column("tags", Json, nullable=False, default=list),
    Column("trade", Json),
    Column("entry_date", String(10), nullable=False),
    Column("is_demo", Boolean, nullable=False, default=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    Column("updated_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"), _ts("updated_at"),
)

attachments = Table(
    "attachments", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("journal_entry_id", Uuid, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False),
    Column("filename", String(200), nullable=False),
    Column("content_type", String(80), nullable=False),
    Column("size", Integer, nullable=False),
    Column("storage", String(16), nullable=False),  # local | supabase
    Column("path", String(400), nullable=False),
    Column("created_by", Uuid, ForeignKey("profiles.id")),
    _ts("created_at"),
)

audit_events = Table(
    "audit_events", metadata,
    Column("id", Uuid, primary_key=True, default=new_id), _ws(),
    Column("actor_id", Uuid, ForeignKey("profiles.id")),
    Column("action", String(40), nullable=False),
    Column("entity", String(40), nullable=False),
    Column("entity_id", String(64)),
    Column("detail", Json),
    _ts("created_at"),
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = get_settings()
        url = s.effective_database_url
        if url.startswith("postgres://") or url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.split("://", 1)[1]
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        else:
            _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _engine


def reset_engine() -> None:
    """Tests: drop the cached engine after changing settings."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


@contextmanager
def tx(user_id: uuid.UUID | str | None, email: str | None = None) -> Iterator[Connection]:
    """One transaction. On Postgres it runs as `authenticated` with the user's claims,
    so RLS decides what the statement can see and change."""
    with get_engine().begin() as conn:
        if conn.dialect.name == "postgresql":
            if not user_id:
                raise RuntimeError("a Postgres transaction needs a user id for RLS")
            claims = json.dumps({"sub": str(user_id), "role": "authenticated", "email": email or ""})
            conn.execute(text("select set_config('request.jwt.claims', :c, true)"), {"c": claims})
            conn.execute(text("set local role authenticated"))
        yield conn


def create_demo_schema() -> None:
    metadata.create_all(get_engine())
