"""Runtime settings, read from the environment (and backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

APP_VERSION = "0.1.0"
ENGINE_VERSION = "day-trader-skill 2.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # "demo": local SQLite workspace and a local demo session, no Supabase.
    # "supabase": Supabase Auth JWTs and the Supabase Postgres database (RLS on).
    # "public": shared lab open to anyone with the link. No login; every request runs as a
    #           server-side technical identity that is a member of DP_PUBLIC_WORKSPACE_ID only.
    dp_auth_mode: Literal["demo", "supabase", "public"] = "demo"

    # Public shared lab (DP_AUTH_MODE=public). Never read from the request.
    dp_public_workspace_id: str = ""
    # Optional. Default: a UUID derived from the workspace id (see auth.public_identity_id).
    dp_public_identity_id: str = ""

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Legacy HS256 projects only. Projects on asymmetric signing keys are verified via JWKS.
    supabase_jwt_secret: str = ""
    # Server only. Used for the private Storage buckets (snapshots, attachments).
    # Accepts a new secret key (sb_secret_...) or the legacy service_role JWT.
    supabase_service_role_key: str = ""
    # Where snapshot and attachment files live: "auto" = Supabase Storage when SUPABASE_URL and
    # SUPABASE_SERVICE_ROLE_KEY are set, local disk otherwise.
    dp_storage: Literal["auto", "local", "supabase"] = "auto"

    dp_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    dp_data_dir: Path = BACKEND_DIR / ".data"
    dp_skill_dir: Path = BACKEND_DIR / "vendor" / "day_trader_skill"

    dp_job_workers: int = Field(default=2, ge=1, le=8)
    dp_job_timeout_s: int = Field(default=600, ge=10, le=3600)
    # Jobs queued or running at the same time in one workspace. Beyond it: HTTP 429 queue_full.
    dp_max_active_jobs: int = Field(default=4, ge=1, le=50)
    # ... and per client (IP), so one visitor cannot hold the whole queue.
    dp_max_active_jobs_per_client: int = Field(default=2, ge=1, le=50)
    # Total size of journal images stored for the workspace.
    dp_max_attachment_storage_mb: int = Field(default=500, ge=1)
    # On start, jobs left queued/running by a previous process are marked as interrupted.
    # Only safe with a single backend instance (the default on Render's free plan).
    dp_mark_interrupted_on_start: bool = True

    # Request limits, per client IP, per minute (0 disables a limit).
    dp_rate_limit_per_min: int = Field(default=180, ge=0)
    dp_rate_limit_writes_per_min: int = Field(default=40, ge=0)
    dp_rate_limit_jobs_per_min: int = Field(default=6, ge=0)
    # Reads that call external providers or engine subprocesses (quotes, charts, news, fundamentals).
    dp_rate_limit_heavy_per_min: int = Field(default=30, ge=0)
    # Engine subprocesses started by requests (news, fundamentals) at the same time, server-wide.
    dp_max_inline_engines: int = Field(default=2, ge=1, le=16)
    # Proxies in front of the backend that append to X-Forwarded-For (1 on Render). 0 = socket peer.
    dp_trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    # Largest request body accepted (JSON); uploads have their own limit.
    dp_max_body_bytes: int = Field(default=256 * 1024, ge=1024)
    dp_max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)

    # SEC asks for "Name email" in the User-Agent. Needed by News (8-K) and Analyst.
    sec_user_agent: str = ""

    # Alpaca Market Data (Basic plan, IEX feed). Server only, never sent to the browser.
    alpaca_api_key_id: str = ""
    alpaca_api_secret_key: str = ""

    # Display policy (see services/policy.py). Empty = the default for the mode: everything
    # visible in the local demo, restrictive in the public lab. Applied by the API, not the UI.
    dp_show_raw_prices: bool | None = None          # OHLCV, quotes and price series
    dp_show_trigger_prices: bool | None = None      # the price on a signal (kept for the next blocks)
    dp_pelosi_public: bool = False                  # waits for the legal review of 5 U.S.C. 13107
    dp_allow_unofficial_sources: bool | None = None  # Yahoo Finance (unofficial; terms forbid automated use)

    @property
    def is_demo(self) -> bool:
        return self.dp_auth_mode == "demo"

    @property
    def is_public(self) -> bool:
        return self.dp_auth_mode == "public"

    @field_validator("dp_show_raw_prices", "dp_show_trigger_prices", "dp_allow_unofficial_sources",
                     "dp_pelosi_public", mode="before")
    @classmethod
    def _blank_is_default(cls, v: object, info) -> object:  # noqa: ANN001
        """An empty line in .env (as in .env.example) means "use the mode's default"."""
        if isinstance(v, str) and not v.strip():
            return False if info.field_name == "dp_pelosi_public" else None
        return v

    def _policy(self, value: bool | None) -> bool:
        return (not self.is_public) if value is None else value

    @property
    def show_raw_prices(self) -> bool:
        return self._policy(self.dp_show_raw_prices)

    @property
    def show_trigger_prices(self) -> bool:
        return self._policy(self.dp_show_trigger_prices)

    @property
    def allow_unofficial_sources(self) -> bool:
        return self._policy(self.dp_allow_unofficial_sources)

    @property
    def storage_backend(self) -> str:
        if self.dp_storage != "auto":
            return self.dp_storage
        return "supabase" if (self.supabase_url and self.supabase_service_role_key) else "local"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.is_demo:
            return "sqlite:///" + (self.dp_data_dir / "darkpool-demo.sqlite").as_posix()
        if self.is_public:
            # Local development only: the public mode on the local SQLite file.
            return "sqlite:///" + (self.dp_data_dir / "darkpool-demo.sqlite").as_posix()
        raise RuntimeError("DATABASE_URL is required when DP_AUTH_MODE=supabase")

    @property
    def is_postgres(self) -> bool:
        return self.effective_database_url.startswith("postgres")

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.dp_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.dp_data_dir.mkdir(parents=True, exist_ok=True)
    return s
