"""SQLAlchemy models for the rebuilt quant system."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class StrategyTemplate(Base):
    __tablename__ = "strategy_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class StrategyInstance(Base):
    __tablename__ = "strategy_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account_configs.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    broker_mode: Mapped[str] = mapped_column(String(32), default="okx_demo", nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), default="spot", nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="BTC/USDT", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), default="1m", nullable=False)
    initial_equity: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    order_usdt: Mapped[float] = mapped_column(Float, default=500.0, nullable=False)
    fee_rate: Mapped[float] = mapped_column(Float, default=0.001, nullable=False)
    slippage_rate: Mapped[float] = mapped_column(Float, default=0.0005, nullable=False)
    allow_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("name", name="uq_strategy_instances_name"),)


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="seed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("market_type", "symbol", "timeframe", "ts", name="uq_candles_identity"),
        Index("ix_candles_lookup", "market_type", "symbol", "timeframe", "ts"),
    )


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    runs: Mapped[list["BacktestRun"]] = relationship(back_populates="experiment")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initial_equity: Mapped[float] = mapped_column(Float, nullable=False)
    final_equity: Mapped[float] = mapped_column(Float, nullable=False)
    total_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    annual_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe: Mapped[float] = mapped_column(Float, nullable=False)
    calmar: Mapped[float] = mapped_column(Float, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_paid: Mapped[float] = mapped_column(Float, nullable=False)
    promotion_status: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), default="unknown", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    experiment: Mapped[Experiment | None] = relationship(back_populates="runs")

    __table_args__ = (Index("ix_backtest_runs_rank", "experiment_id", "total_return_pct", "max_drawdown_pct"),)


class EquityPoint(Base):
    __tablename__ = "equity_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_equity_points_run_ts", "run_id", "ts"),)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"), nullable=True)
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_instances.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account_configs.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    broker_mode: Mapped[str] = mapped_column(String(32), default="okx_demo", nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), default="spot", nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), default="market", nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_trades_scope", "run_id", "instance_id", "ts"),
        Index("ix_trades_account_ts", "account_id", "ts"),
    )


class GridState(Base):
    __tablename__ = "grid_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_instances.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AccountConfig(Base):
    __tablename__ = "account_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), default="okx_demo", nullable=False)  # okx_demo, okx_live
    api_key: Mapped[str] = mapped_column(String(256), nullable=False)
    api_secret: Mapped[str] = mapped_column(String(256), nullable=False)
    passphrase: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("name", name="uq_account_configs_name"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_audit_events_ts", "ts"),)
