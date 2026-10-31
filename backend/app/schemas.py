"""Request models. Everything a user can send is validated here before it can
reach the database or an engine argument list."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from .services.market_data import SYMBOL_RE

Symbol = Annotated[str, Field(min_length=1, max_length=7)]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _sym(v: str) -> str:
    v = v.strip().upper()
    if not SYMBOL_RE.match(v):
        raise ValueError("ticker inválido (1 a 5 letras, opcionalmente .A)")
    return v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------- strategies

RuleType = Literal["orb", "breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce",
                   "sma_cross", "macd_cross"]

PARAM_LIMITS: dict[str, dict[str, tuple[float, float, float]]] = {
    # name: (min, max, default)
    "orb": {"or_minutes": (5, 60, 15)},
    "breakout_20d": {"lookback": (5, 120, 20)},
    "bull_flag": {"pole_pct": (3, 50, 10), "flag_days": (3, 15, 5), "flag_range_pct": (1, 15, 5)},
    "reclaim_ma20": {"period": (5, 200, 20)},
    "oversold": {"rsi_period": (2, 50, 14), "threshold": (5, 50, 30)},
    "oversold_bounce": {"rsi_period": (2, 50, 14), "threshold": (5, 50, 30)},
    "sma_cross": {"fast": (2, 100, 20), "slow": (5, 300, 50)},
    "macd_cross": {"fast": (2, 50, 12), "slow": (5, 100, 26), "signal": (2, 50, 9)},
}


class Rule(Strict):
    type: RuleType
    params: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_params(self) -> Rule:
        limits = PARAM_LIMITS[self.type]
        unknown = set(self.params) - set(limits)
        if unknown:
            raise ValueError(f"parâmetros não suportados para {self.type}: {sorted(unknown)}")
        clean = {}
        for k, (lo, hi, default) in limits.items():
            v = float(self.params.get(k, default))
            if not lo <= v <= hi:
                raise ValueError(f"{k} deve estar entre {lo:g} e {hi:g}")
            clean[k] = v
        if self.type == "orb" and int(clean["or_minutes"]) % 5:
            raise ValueError("a faixa de abertura deve ser múltipla de 5 minutos")
        if self.type in ("sma_cross", "macd_cross") and clean["fast"] >= clean["slow"]:
            raise ValueError("a média rápida deve ser menor que a lenta")
        self.params = clean
        return self


class ExitRule(Strict):
    stop_type: Literal["pct", "atr", "or_mid", "or_low"] = "pct"
    stop_value: float = Field(default=2.0, ge=0, le=50)
    target_r: float = Field(default=2.0, ge=0.25, le=10)
    max_hold_bars: int = Field(default=10, ge=1, le=120)
    flat_by: str = "15:55"

    @field_validator("flat_by")
    @classmethod
    def check_hhmm(cls, v: str) -> str:
        if not HHMM.match(v) or not "09:45" <= v <= "16:00":
            raise ValueError("horário de saída entre 09:45 e 16:00 (Nova York)")
        return v


class Filters(Strict):
    min_price: float = Field(default=5, ge=0, le=100000)
    min_avg_volume: float = Field(default=0, ge=0, le=1e10)


class RiskRules(Strict):
    account_size: float = Field(default=10000, gt=0, le=1e9)
    max_loss_per_trade: float = Field(default=100, gt=0, le=1e7)
    max_position_pct: float = Field(default=50, gt=0, le=100)
    daily_loss_limit: float = Field(default=300, gt=0, le=1e7)
    max_trades_per_day: int = Field(default=3, ge=1, le=50)
    min_reward_risk: float = Field(default=1.0, ge=0, le=10)


class StrategyConfig(Strict):
    symbol: Symbol
    rule: Rule
    exit: ExitRule = Field(default_factory=ExitRule)
    filters: Filters = Field(default_factory=Filters)
    risk: RiskRules = Field(default_factory=RiskRules)

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str) -> str:
        return _sym(v)

    @model_validator(mode="after")
    def check_coherent(self) -> StrategyConfig:
        if self.rule.type == "orb" and self.exit.stop_type == "atr":
            raise ValueError("ORB aceita stop no meio da faixa, na mínima da faixa ou em %")
        if self.rule.type != "orb" and self.exit.stop_type in ("or_mid", "or_low"):
            raise ValueError("stops pela faixa de abertura só valem para ORB")
        if self.exit.stop_type in ("pct", "atr") and self.exit.stop_value <= 0:
            raise ValueError("o stop precisa de um valor maior que zero")
        return self


class StrategyCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=4000)
    config: StrategyConfig
    note: str = Field(default="", max_length=280)


class StrategyUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    config: StrategyConfig | None = None
    note: str = Field(default="", max_length=280)
    archived: bool | None = None


class BacktestRequest(Strict):
    strategy_id: uuid.UUID
    version: int | None = Field(default=None, ge=1)
    snapshot_id: uuid.UUID | None = None
    range: Literal["1y", "2y", "5y"] = "2y"
    split_date: dt.date | None = None
    # NYSE sessions of 5-minute bars for an ORB backtest downloaded from Alpaca. Ignored with a
    # snapshot, with Yahoo (fixed 60 days) and by daily rules.
    history_sessions: int = Field(default=60, ge=20, le=250)


# ---------------------------------------------------------------- time machine

class PlanRule(Strict):
    """The ORB plan as a rule: the server finds entry, stop and target on the plan day's own bars
    (trader-entry + trader-exit), so the visitor never has to see or send provider prices."""
    or_minutes: int = Field(default=15, ge=5, le=60)
    stop_rule: Literal["or_mid", "or_low", "pct", "atr"] = "or_mid"
    stop_pct: float = Field(default=1.0, gt=0, le=50)
    atr_k: float = Field(default=1.5, ge=0.25, le=10)
    target_r: float = Field(default=1.0, ge=0.25, le=10)

    @model_validator(mode="after")
    def check_grid(self) -> PlanRule:
        if self.or_minutes % 5:
            raise ValueError("faixa de abertura em múltiplos de 5 minutos")
        return self


class TimeMachineRequest(Strict):
    symbol: Symbol
    date: dt.date
    # Either the plan in prices (entry, stop, target, entry_time) or plan_rule (computed on the server).
    entry: float | None = Field(default=None, gt=0, lt=1e6)
    stop: float | None = Field(default=None, gt=0, lt=1e6)
    target: float | None = Field(default=None, gt=0, lt=1e6)
    entry_time: str | None = None
    plan_rule: PlanRule | None = None
    replays: int = Field(default=10000, ge=100, le=50000)
    seed: int = Field(default=19, ge=0, le=2**31 - 1)
    window: int = Field(default=2, ge=0, le=10)
    until: str | None = None
    or_minutes: int = Field(default=15, ge=5, le=60)
    snapshot_id: uuid.UUID | None = None
    # NYSE sessions before the plan's day downloaded from Alpaca. Ignored with a snapshot and
    # with Yahoo (fixed 60 days).
    history_sessions: int = Field(default=60, ge=20, le=250)
    strategy_id: uuid.UUID | None = None
    title: str = Field(default="", max_length=160)

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str) -> str:
        return _sym(v)

    @field_validator("entry_time", "until")
    @classmethod
    def check_grid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not HHMM.match(v):
            raise ValueError("use HH:MM (horário de Nova York)")
        h, m = map(int, v.split(":"))
        mins = h * 60 + m
        if mins % 5 or not 9 * 60 + 35 <= mins <= 16 * 60:
            raise ValueError("horário na grade de 5 minutos entre 09:35 e 16:00")
        return v

    @model_validator(mode="after")
    def check_plan(self) -> TimeMachineRequest:
        prices = (self.entry, self.stop, self.target, self.entry_time)
        if self.plan_rule is not None:
            if any(x is not None for x in prices):
                raise ValueError("envie o plano em preços ou a regra (plan_rule), não os dois")
            self.or_minutes = self.plan_rule.or_minutes
        else:
            if any(x is None for x in prices):
                raise ValueError("informe entrada, stop, alvo e horário, ou a regra do plano (plan_rule)")
            if not self.stop < self.entry < self.target:
                raise ValueError("compra: o stop deve ficar abaixo da entrada e o alvo acima")
        if self.or_minutes % 5:
            raise ValueError("faixa de abertura em múltiplos de 5 minutos")
        if self.date > dt.date.today():
            raise ValueError("a data não pode estar no futuro")
        return self


# ---------------------------------------------------------------- scanner

class ScanRequest(Strict):
    mode: Literal["daily", "orb"] = "daily"
    source: Literal["symbols", "watchlist", "universe"] = "symbols"
    symbols: list[Symbol] = Field(default_factory=list, max_length=300)
    watchlist_id: uuid.UUID | None = None
    limit: int = Field(default=200, ge=1, le=6000)
    min_price: float = Field(default=5, ge=0, le=100000)
    min_volume: int = Field(default=1_000_000, ge=0, le=10**10)
    # orb only: the opening range, the session (default: today) and the clock cut (HH:MM New York;
    # default: now, or 15:30 for a past day; never later than the data the provider can serve).
    or_minutes: int = Field(default=15, ge=5, le=120)
    day: dt.date | None = None
    at: str | None = None

    @field_validator("symbols")
    @classmethod
    def check_symbols(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for s in v:
            s = _sym(s)
            if s not in out:
                out.append(s)
        return out

    @field_validator("at")
    @classmethod
    def check_at(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not HHMM.match(v):
            raise ValueError("use HH:MM (horário de Nova York)")
        h, m = map(int, v.split(":"))
        if (h * 60 + m) % 5 or not 9 * 60 + 35 <= h * 60 + m <= 16 * 60:
            raise ValueError("horário na grade de 5 minutos entre 09:35 e 16:00")
        return v

    @model_validator(mode="after")
    def check_mode(self) -> ScanRequest:
        if self.or_minutes % 5:
            raise ValueError("faixa de abertura em múltiplos de 5 minutos")
        if self.mode == "daily" and (self.day or self.at):
            raise ValueError("dia e horário valem só para a varredura ORB")
        if self.day and self.day > dt.date.today():
            raise ValueError("a data não pode estar no futuro")
        return self


# ---------------------------------------------------------------- watchlists / journal / settings

class WatchlistCreate(Strict):
    name: str = Field(min_length=1, max_length=80)


class WatchlistAssetAdd(Strict):
    symbol: Symbol
    note: str = Field(default="", max_length=280)
    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str) -> str:
        return _sym(v)


JournalKind = Literal["note", "hypothesis", "simulated_trade", "lesson", "error"]


class SimTrade(Strict):
    side: Literal["buy"] = "buy"
    entry: float = Field(gt=0, lt=1e6)
    stop: float = Field(gt=0, lt=1e6)
    exit: float | None = Field(default=None, gt=0, lt=1e6)
    shares: int | None = Field(default=None, ge=1, le=10**7)

    @model_validator(mode="after")
    def check_trade(self) -> SimTrade:
        if self.stop >= self.entry:
            raise ValueError("o stop deve ficar abaixo da entrada")
        return self


class JournalWrite(Strict):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=20000)
    kind: JournalKind = "note"
    symbol: Symbol | None = None
    strategy_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(default_factory=list, max_length=12)
    trade: SimTrade | None = None
    entry_date: dt.date = Field(default_factory=dt.date.today)

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str | None) -> str | None:
        return _sym(v) if v else None

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v: list[str]) -> list[str]:
        return sorted({t.strip().lower() for t in v if t.strip()})


class ProfileUpdate(Strict):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferences: dict | None = None

    @field_validator("preferences")
    @classmethod
    def check_prefs(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        allowed = {"reduced_motion", "density", "default_replays", "default_seed", "default_min_price",
                   "default_min_volume", "default_range"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"preferências desconhecidas: {sorted(bad)}")
        return v


class RiskCheckRequest(Strict):
    symbol: Symbol
    date: dt.date
    entry: float = Field(gt=0, lt=1e6)
    stop: float = Field(gt=0, lt=1e6)
    target: float = Field(gt=0, lt=1e6)
    entry_time: str = "10:15"
    risk: RiskRules = Field(default_factory=RiskRules)
    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str) -> str:
        return _sym(v)

    @model_validator(mode="after")
    def check_plan(self) -> RiskCheckRequest:
        if not self.stop < self.entry < self.target:
            raise ValueError("compra: stop < entrada < alvo")
        if not HHMM.match(self.entry_time):
            raise ValueError("horário HH:MM")
        return self


class OrbPlanRequest(Strict):
    # A frozen snapshot, or a symbol: then the plan day's own bars are downloaded from the
    # provider chosen for new 5-minute bars (DP_INTRADAY_PROVIDER) and frozen first.
    snapshot_id: uuid.UUID | None = None
    symbol: Symbol | None = None
    date: dt.date
    or_minutes: int = Field(default=15, ge=5, le=60)
    stop_rule: Literal["or_mid", "or_low", "pct", "atr"] = "or_mid"
    stop_pct: float = Field(default=1.0, gt=0, le=50)
    # atr:K = K x the 14-bar ATR of the session's bars up to the entry bar (trader-exit).
    atr_k: float = Field(default=1.5, ge=0.25, le=10)
    target_r: float = Field(default=1.0, ge=0.25, le=10)

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str | None) -> str | None:
        return None if v is None else _sym(v)

    @model_validator(mode="after")
    def check_grid(self) -> OrbPlanRequest:
        if self.or_minutes % 5:
            raise ValueError("faixa de abertura em múltiplos de 5 minutos")
        if self.snapshot_id is None and self.symbol is None:
            raise ValueError("informe um snapshot ou um ticker")
        if self.date > dt.date.today():
            raise ValueError("a data não pode estar no futuro")
        return self


# ---------------------------------------------------------------- alerts (trader-alerts, Bloco 5)

class AlertRule(Strict):
    """One trader-alerts rule (the engine's own format; it validates again)."""
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:\-]{1,40}$")
    type: Literal["above", "below", "stop", "target", "pct_move", "opening_bell", "time"]
    symbol: Symbol | None = None
    price: float | None = Field(default=None, gt=0, lt=1e6)
    pct: float | None = Field(default=None, gt=0, le=100)
    direction: Literal["up", "down"] | None = None
    ref: float | None = Field(default=None, gt=0, lt=1e6)
    at: str | None = None
    label: str | None = Field(default=None, max_length=60)
    before_close: bool | None = None
    date: dt.date | None = None
    rearm: bool | None = None
    note: str | None = Field(default=None, max_length=120)

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, v: str | None) -> str | None:
        return None if v is None else _sym(v)

    @field_validator("at")
    @classmethod
    def check_at(cls, v: str | None) -> str | None:
        if v is not None and not HHMM.match(v):
            raise ValueError("use HH:MM (horário de Nova York)")
        return v

    @field_serializer("date")
    def ser_date(self, v: dt.date | None) -> str | None:
        return v.isoformat() if v else None


class AlertState(Strict):
    """What already rang (rule id -> UTC stamp), kept by the visitor's browser."""
    rung: dict[str, str] = Field(default_factory=dict, max_length=200)
    last_check: str | None = Field(default=None, max_length=24)


class AlertCheckRequest(Strict):
    rules: list[AlertRule] = Field(min_length=1, max_length=50)
    state: AlertState = Field(default_factory=AlertState)
