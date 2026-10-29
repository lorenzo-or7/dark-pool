"""Runtime settings, read from the environment (and backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    dp_auth_mode: Literal["demo", "supabase"] = "demo"

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Legacy HS256 projects only. Projects on asymmetric signing keys are verified via JWKS.
    supabase_jwt_secret: str = ""

    dp_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    dp_data_dir: Path = BACKEND_DIR / ".data"
    dp_skill_dir: Path = BACKEND_DIR / "vendor" / "day_trader_skill"

    dp_job_workers: int = Field(default=2, ge=1, le=8)
    dp_job_timeout_s: int = Field(default=600, ge=10, le=3600)

    # SEC asks for "Name email" in the User-Agent. Needed by News (8-K) and Analyst.
    sec_user_agent: str = ""

    @property
    def is_demo(self) -> bool:
        return self.dp_auth_mode == "demo"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.is_demo:
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
