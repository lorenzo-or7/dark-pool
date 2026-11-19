"""Settings of the paper-trading agent. Read from the same .env files as the backend, with their own
names, so the web app's settings stay unchanged. Paper keys are separate from the market-data keys:
Alpaca gives the paper account its own key pair (https://docs.alpaca.markets/docs/paper-trading).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..config import BACKEND_DIR, ROOT_DIR


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
                                      env_file_encoding="utf-8", extra="ignore")

    # off = does nothing; dry_run = computes the signals and writes what it WOULD send, no broker call;
    # paper = sends bracket orders to the Alpaca PAPER account (simulated money).
    dp_agent_mode: Literal["off", "dry_run", "paper"] = "off"

    # Keys of the Alpaca paper account (not the market-data keys). Never in code, logs or commits.
    alpaca_paper_key_id: str = ""
    alpaca_paper_secret_key: str = ""

    # Comma-separated US tickers to watch, e.g. SPY,QQQ,AAPL. Empty = the agent refuses to run.
    dp_agent_symbols: str = ""

    # Strategy: the lab's ORB plan (trader-entry + trader-exit), same parameters as POST /api/plan/orb.
    dp_agent_or_minutes: int = Field(default=15, ge=5, le=60)
    dp_agent_stop_rule: Literal["or_mid", "or_low", "pct", "atr"] = "or_mid"
    dp_agent_stop_pct: float = Field(default=1.0, gt=0, le=20)
    dp_agent_atr_k: float = Field(default=1.5, gt=0, le=10)
    dp_agent_target_r: float = Field(default=1.0, gt=0, le=10)

    # Risk limits (US$ of the paper account).
    dp_agent_risk_per_trade_usd: float = Field(default=50.0, gt=0)
    dp_agent_max_position_usd: float = Field(default=2000.0, gt=0)
    dp_agent_max_trades_per_day: int = Field(default=3, ge=1, le=50)
    dp_agent_max_daily_loss_usd: float = Field(default=150.0, gt=0)

    # A trigger older than this is skipped (the price has moved since the bar closed).
    dp_agent_max_signal_age_min: int = Field(default=10, ge=1, le=60)
    # The entry is a limit order at the trigger price plus this tolerance, never a market order. In R
    # (fractions of the planned risk per share), so a tight stop gets a tight tolerance: 0.1 = 10% of R.
    dp_agent_max_entry_slippage_r: float = Field(default=0.1, ge=0, le=0.5)
    # Everything is closed this many minutes before the NYSE close (also on early-close days).
    dp_agent_flatten_minutes_before_close: int = Field(default=5, ge=1, le=60)
    # Seconds between two checks in `run`.
    dp_agent_poll_s: int = Field(default=30, ge=10, le=300)

    @field_validator("dp_agent_mode", "dp_agent_stop_rule", mode="before")
    @classmethod
    def _lower(cls, v: object, info) -> object:  # noqa: ANN001
        if isinstance(v, str):
            v = v.strip().lower()
            if not v:
                return "off" if info.field_name == "dp_agent_mode" else "or_mid"
        return v

    @property
    def symbols(self) -> list[str]:
        out: list[str] = []
        for s in self.dp_agent_symbols.replace(";", ",").split(","):
            s = s.strip().upper()
            if s and s not in out:
                out.append(s)
        return out

    @property
    def paper_keys_set(self) -> bool:
        return bool(self.alpaca_paper_key_id and self.alpaca_paper_secret_key)


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
