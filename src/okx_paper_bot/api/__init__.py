"""FastAPI application for the OKX quant workbench."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from okx_paper_bot.brokers import OKXGateway, okx_inst_id
from okx_paper_bot.config import AppSettings
from okx_paper_bot.experiments import ExperimentService, ExperimentSpec
from okx_paper_bot.market import MarketDataService, ensure_utc, timeframe_seconds
from okx_paper_bot.persistence.db import Database
from okx_paper_bot.persistence.db import create_database
from okx_paper_bot.persistence.models import (
    AccountConfig,
    AuditEvent,
    BacktestRun,
    Candle,
    EquityPoint,
    Experiment,
    StrategyInstance,
    StrategyTemplate,
    SystemConfig,
    Trade,
)
from okx_paper_bot.risk import LiveSafetyGate, LiveTradeRequest
from okx_paper_bot.runner import RunnerManager
from okx_paper_bot.strategies import strategy_templates


class InstancePayload(BaseModel):
    name: str
    strategy_key: str = "ma_crossover"
    account_id: int | None = None
    enabled: bool = False
    broker_mode: str = "okx_demo"
    market_type: str = "spot"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    initial_equity: float = 10000.0
    order_usdt: float = 500.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    allow_live: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class ExperimentPayload(BaseModel):
    name: str = "MA sweep"
    strategy_instance_id: int | None = None
    strategy_key: str = "ma_crossover"
    market_type: str = "spot"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    initial_equity: float = 10000.0
    order_usdt: float = 500.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    fixed_params: dict[str, Any] = Field(default_factory=dict)
    param_grid: dict[str, list[Any]] = Field(default_factory=lambda: {"fast": [5, 8, 13], "slow": [20, 34]})
    description: str = ""
    data_source: str = "cached"
    start_date: date | None = None
    end_date: date | None = None
    candles_limit: int | None = Field(default=None, ge=3, le=1000)


class BacktestPayload(BaseModel):
    strategy_key: str = "ma_crossover"
    strategy_params: dict[str, Any] = Field(default_factory=lambda: {"fast": 5, "slow": 20})
    market_type: str = "spot"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    initial_equity: float = 10000.0
    order_usdt: float = 500.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    start_date: date | None = None
    end_date: date | None = None
    candles_limit: int | None = Field(default=None, ge=3, le=1000)


class PromotePayload(BaseModel):
    status: str


class InstanceStatusPayload(BaseModel):
    status: str
    confirmation: str | None = None


class InstanceOrderPayload(BaseModel):
    side: str = "buy"
    quote_usdt: float = Field(default=5.0, gt=0)
    amount: float | None = Field(default=None, gt=0)
    confirmation: str | None = None


class CandleSyncPayload(BaseModel):
    market_type: str = "spot"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    limit: int = 300
    source: str = "okx"


class CredentialPayload(BaseModel):
    okx_api_key: str | None = None
    okx_api_secret: str | None = None
    okx_api_password: str | None = None


class LiveSettingsPayload(BaseModel):
    confirmation: str | None = None


class LiveValidationPayload(BaseModel):
    broker_mode: str = "okx_live"
    instance_allow_live: bool = False
    confirmation: str | None = None


class AccountPayload(BaseModel):
    name: str
    account_type: str = "okx_demo"
    api_key: str
    api_secret: str
    passphrase: str
    is_active: bool = True


class AccountUpdatePayload(BaseModel):
    name: str | None = None
    account_type: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None
    is_active: bool | None = None


class DemoBalanceAdjustPayload(BaseModel):
    type: str = "increase"
    ccy: str = "USDT"
    amt: str = "5000"


_CREDENTIAL_KEYS = ("okx_api_key", "okx_api_secret", "okx_api_password")
AUTO_FETCH_BATCH_CANDLES = 5000
DEFAULT_BACKTEST_RANGE_DAYS = 30
DEMO_BALANCE_CURRENCIES = {"BTC", "ETH", "USDT", "OKB"}
DEMO_BALANCE_INCREASE_LIMITS = {
    "BTC": Decimal("1"),
    "ETH": Decimal("1"),
    "USDT": Decimal("5000"),
    "OKB": Decimal("100"),
}


def _load_settings_from_db(database: Database, base: AppSettings) -> AppSettings:
    overrides: dict[str, str] = {}
    with database.session() as session:
        for key in _CREDENTIAL_KEYS:
            row = session.get(SystemConfig, key)
            if row and row.value:
                overrides[key] = row.value
    return replace(base, **overrides) if overrides else base


def _save_settings_to_db(database: Database, settings: AppSettings) -> None:
    with database.session() as session:
        for key in _CREDENTIAL_KEYS:
            value = getattr(settings, key, "")
            existing = session.get(SystemConfig, key)
            if existing:
                existing.value = value
            else:
                session.add(SystemConfig(key=key, value=value))


def _coerce_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"invalid date value: {value!r}")


def _latest_completed_candle_start(timeframe: str) -> datetime:
    seconds = timeframe_seconds(timeframe)
    now = datetime.now(timezone.utc)
    current_start_epoch = int(now.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(current_start_epoch - seconds, tz=timezone.utc)


def _backtest_range_bounds(data: dict[str, Any]) -> tuple[datetime, datetime, datetime, datetime, int]:
    end_day = _coerce_date(data.get("end_date")) or datetime.now(timezone.utc).date()
    start_day = _coerce_date(data.get("start_date")) or (end_day - timedelta(days=DEFAULT_BACKTEST_RANGE_DAYS))
    if start_day > end_day:
        raise ValueError("start_date must be before or equal to end_date")

    requested_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    requested_end = datetime.combine(end_day, time.max, tzinfo=timezone.utc)
    actual_end = min(requested_end, _latest_completed_candle_start(str(data["timeframe"])))
    if requested_start > actual_end:
        raise ValueError("date range contains no completed candles yet")

    seconds = timeframe_seconds(str(data["timeframe"]))
    expected = int((actual_end - requested_start).total_seconds() // seconds) + 1
    if expected < 3:
        raise ValueError("date range is too short; choose at least three completed candles")
    return requested_start, actual_end, requested_start, requested_end, expected


def _settings_for_account(row: AccountConfig, base: AppSettings | None = None) -> AppSettings:
    active = base or AppSettings()
    return replace(
        active,
        okx_api_key=row.api_key,
        okx_api_secret=row.api_secret,
        okx_api_password=row.passphrase,
    )


def _okx_error_message(data: dict[str, Any], fallback: str = "OKX 官方 API 返回错误") -> str:
    return str(data.get("msg") or data.get("message") or fallback)


def _parse_order_error(raw_error: Any) -> dict[str, Any]:
    raw = "" if raw_error is None else str(raw_error)
    payload: dict[str, Any] | None = None
    code: str | None = None
    sub_code: str | None = None
    message: str | None = None
    exchange_message: str | None = None

    json_start = raw.find("{")
    if json_start >= 0:
        try:
            parsed = json.loads(raw[json_start:])
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None

    if payload:
        code = str(payload.get("code")) if payload.get("code") not in (None, "") else None
        exchange_message = str(payload.get("msg") or payload.get("message") or "") or None
        rows = payload.get("data")
        first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        if first:
            code = str(first.get("sCode") or first.get("code") or code or "") or None
            sub_code = str(first.get("subCode") or "") or None
            exchange_message = str(first.get("sMsg") or first.get("msg") or exchange_message or "") or None
        message = exchange_message or code

    if not message:
        if raw.startswith("okx GET ") or raw.startswith("okx POST "):
            message = f"OKX API 请求超时或不可达：{raw.removeprefix('okx ').strip()}"
        else:
            message = raw or "未知下单错误"

    return {
        "code": code,
        "sub_code": sub_code,
        "message": message,
        "exchange_message": exchange_message,
        "raw": raw or None,
    }


def _first_value(row: dict[str, Any], *keys: str, default: str = "0") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _parse_okx_account_balance(data: dict[str, Any]) -> tuple[dict[str, dict[str, str]], str | None]:
    items = data.get("data") if isinstance(data, dict) else None
    account = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    details = account.get("details") if isinstance(account, dict) else []
    balances: dict[str, dict[str, str]] = {}
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            currency = str(detail.get("ccy") or "").upper()
            if not currency:
                continue
            balances[currency] = {
                "free": _first_value(detail, "availBal", "availEq", "cashBal"),
                "used": _first_value(detail, "frozenBal"),
                "total": _first_value(detail, "eq", "cashBal", "availBal"),
            }
    total_eq = str(account.get("totalEq")) if isinstance(account, dict) and account.get("totalEq") not in (None, "") else None
    return balances, total_eq


def _account_type_for_mode(broker_mode: str) -> str:
    if broker_mode == "okx_live":
        return "okx_live"
    if broker_mode in {"okx_demo", "paper"}:
        return "okx_demo"
    raise HTTPException(status_code=400, detail="broker_mode must be okx_demo or okx_live")


def _mode_label(broker_mode: str) -> str:
    return "OKX Live" if _account_type_for_mode(broker_mode) == "okx_live" else "OKX Demo"


def _default_account_for_mode(session: Session, broker_mode: str) -> AccountConfig:
    account_type = _account_type_for_mode(broker_mode)
    row = session.scalars(
        select(AccountConfig)
        .where(AccountConfig.account_type == account_type)
        .where(AccountConfig.is_active.is_(True))
        .order_by(AccountConfig.id)
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(status_code=400, detail=f"{_mode_label(broker_mode)} 需要先在账户中心配置启用账户")
    return row


def _require_account_for_mode(session: Session, account_id: int | None, broker_mode: str) -> AccountConfig:
    row = session.get(AccountConfig, account_id) if account_id is not None else _default_account_for_mode(session, broker_mode)
    if row is None:
        raise HTTPException(status_code=404, detail="account not found")
    if not row.is_active:
        raise HTTPException(status_code=400, detail=f"账户 {row.name} 未启用")
    expected = _account_type_for_mode(broker_mode)
    if row.account_type != expected:
        raise HTTPException(status_code=400, detail=f"{_mode_label(broker_mode)} 只能绑定 {expected} 账户")
    return row


def _normalize_instance_payload(data: dict[str, Any], session: Session) -> dict[str, Any]:
    broker_mode = data.get("broker_mode") or "okx_demo"
    if broker_mode not in {"okx_demo", "okx_live"}:
        raise HTTPException(status_code=400, detail="运行中心只支持 OKX Demo 和 OKX Live")
    account = _require_account_for_mode(session, data.get("account_id"), broker_mode)
    data["broker_mode"] = broker_mode
    data["account_id"] = account.id
    return data


def _ensure_instance_account(session: Session, row: StrategyInstance, broker_mode: str) -> AccountConfig:
    account = _require_account_for_mode(session, row.account_id, broker_mode)
    if row.account_id != account.id:
        row.account_id = account.id
    return account


def _extract_order_id(order: Any) -> str | None:
    if not isinstance(order, dict):
        return None
    value = order.get("id") or order.get("orderId") or order.get("ordId")
    if value:
        return str(value)
    info = order.get("info")
    if isinstance(info, dict):
        rows = info.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            value = rows[0].get("ordId") or rows[0].get("orderId")
            return str(value) if value else None
    rows = order.get("data")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        value = rows[0].get("ordId") or rows[0].get("orderId")
        return str(value) if value else None
    return None


def _executed_trades(rows: list[Trade]) -> list[Trade]:
    return [row for row in rows if (row.meta or {}).get("status") != "failed"]


def _instance_net_position(trades: list[Trade]) -> float:
    executed = _executed_trades(trades)
    buy_qty = sum(float(row.amount or 0.0) for row in executed if row.side == "buy")
    sell_qty = sum(float(row.amount or 0.0) for row in executed if row.side == "sell")
    return max(0.0, buy_qty - sell_qty)


def _instance_average_entry(trades: list[Trade]) -> float:
    executed = _executed_trades(trades)
    buy_qty = sum(float(row.amount or 0.0) for row in executed if row.side == "buy")
    buy_notional = sum(float(row.amount or 0.0) * float(row.price or 0.0) for row in executed if row.side == "buy")
    return buy_notional / buy_qty if buy_qty > 0 else 0.0


def _fetch_ticker_price(gateway: OKXGateway, symbol: str) -> float:
    ticker = gateway.fetch_ticker(symbol=symbol)
    price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
    try:
        parsed = float(price)
    except (TypeError, ValueError):
        parsed = 0.0
    if parsed <= 0:
        raise HTTPException(status_code=502, detail="OKX 行情价格不可用")
    return parsed


def _symbol_base_ccy(symbol: str) -> str:
    normalized = symbol.split(":", 1)[0].replace("-", "/")
    return normalized.split("/", 1)[0].upper()


def _fetch_free_balance(gateway: OKXGateway, ccy: str) -> float:
    data = gateway.fetch_account_balance(ccy)
    if data.get("code") != "0":
        raise HTTPException(status_code=502, detail=_okx_error_message(data))
    balances, _ = _parse_okx_account_balance(data)
    try:
        return float(balances.get(ccy.upper(), {}).get("free", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _account_trade_summary(trades: list[Trade]) -> dict[str, Any]:
    executed = _executed_trades(trades)
    realized_pnl = sum(float(row.pnl or 0.0) for row in executed)
    fee_paid = sum(float(row.fee or 0.0) for row in executed)
    turnover = sum(float(row.amount or 0.0) * float(row.price or 0.0) for row in executed)
    wins = sum(1 for row in executed if float(row.pnl or 0.0) > 0)
    losses = sum(1 for row in executed if float(row.pnl or 0.0) < 0)
    last_trade = executed[-1] if executed else None
    return {
        "trades_count": len(executed),
        "failed_trades_count": len(trades) - len(executed),
        "buy_count": sum(1 for row in executed if row.side == "buy"),
        "sell_count": sum(1 for row in executed if row.side == "sell"),
        "realized_pnl": realized_pnl,
        "fee_paid": fee_paid,
        "turnover": turnover,
        "win_rate_pct": (wins / (wins + losses) * 100) if wins + losses else 0.0,
        "last_trade_ts": _iso_utc(last_trade.ts) if last_trade else None,
    }


def _build_account_summary(row: AccountConfig, session: Session) -> dict[str, Any]:
    instances = session.scalars(
        select(StrategyInstance)
        .where(StrategyInstance.account_id == row.id)
        .order_by(StrategyInstance.created_at.desc())
    ).all()
    trades = session.scalars(
        select(Trade)
        .where(Trade.account_id == row.id)
        .where(Trade.broker_mode.in_(("okx_demo", "okx_live")))
        .order_by(Trade.ts)
    ).all()
    balance: dict[str, Any]
    positions: dict[str, Any]
    try:
        gateway = OKXGateway(_settings_for_account(row), row.account_type, "spot")
        balance_data = gateway.fetch_account_balance()
        if balance_data.get("code") == "0":
            balances, total_eq = _parse_okx_account_balance(balance_data)
            balance = {"ok": True, "balances": balances, "total_eq": total_eq}
        else:
            balance = {"ok": False, "error": _okx_error_message(balance_data), "code": balance_data.get("code")}
    except Exception as exc:
        balance = {"ok": False, "error": f"OKX 官方 API 不可用: {exc}"}
    try:
        gateway = OKXGateway(_settings_for_account(row), row.account_type, "spot")
        position_data = gateway.fetch_positions()
        if position_data.get("code") == "0":
            positions = {"ok": True, "positions": position_data.get("data") if isinstance(position_data.get("data"), list) else []}
        else:
            positions = {"ok": False, "error": _okx_error_message(position_data), "code": position_data.get("code")}
    except Exception as exc:
        positions = {"ok": False, "error": f"OKX 官方 API 不可用: {exc}"}
    return {
        "account": _serialize_account_brief(row),
        "instances": [_serialize_instance_brief(instance) for instance in instances],
        "running_instances": sum(1 for instance in instances if instance.status in {"okx_demo_running", "okx_live_running"}),
        "trade_stats": _account_trade_summary(list(trades)),
        "balance": balance,
        "positions": positions,
    }


def _validate_demo_balance_adjustment(payload: DemoBalanceAdjustPayload) -> tuple[str, str, str]:
    adjustment_type = payload.type.strip().lower()
    if adjustment_type not in {"increase", "reduce"}:
        raise HTTPException(status_code=400, detail="type must be increase or reduce")

    ccy = payload.ccy.strip().upper()
    if ccy not in DEMO_BALANCE_CURRENCIES:
        raise HTTPException(status_code=400, detail="OKX demo balance adjustment supports BTC, ETH, USDT, OKB")

    amt = payload.amt.strip()
    try:
        amount = Decimal(amt)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="amt must be a valid decimal string") from exc
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amt must be greater than 0")
    if adjustment_type == "increase" and amount > DEMO_BALANCE_INCREASE_LIMITS[ccy]:
        raise HTTPException(
            status_code=400,
            detail=f"OKX demo increase limit for {ccy} is {DEMO_BALANCE_INCREASE_LIMITS[ccy]} per request",
        )
    return adjustment_type, ccy, format(amount, "f")


def create_app(settings: AppSettings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or AppSettings.from_env()
    database = database or create_database(settings)
    database.init_schema()
    settings = _load_settings_from_db(database, settings)

    market_data = MarketDataService()
    experiments = ExperimentService(market_data)
    runner_manager = RunnerManager(settings, database, market_data)
    experiment_jobs: dict[str, Any] = {}
    experiment_jobs_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runner_manager.restore_running_instances()
        yield
        runner_manager.stop_all()

    app = FastAPI(title="OKX Quant Workbench", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.market_data = market_data
    app.state.experiments = experiments
    app.state.experiment_jobs = experiment_jobs
    app.state.experiment_jobs_lock = experiment_jobs_lock
    app.state.runner_manager = runner_manager

    def get_session():
        with database.session() as session:
            yield session

    def current_settings() -> AppSettings:
        return app.state.settings

    def set_job(job_id: str, **updates: Any) -> None:
        with app.state.experiment_jobs_lock:
            job = app.state.experiment_jobs.get(job_id)
            if job is not None:
                job.update(updates)
                job["updated_at"] = datetime.now(timezone.utc)

    def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
        out = dict(job)
        out["created_at"] = _iso_utc(out.get("created_at"))
        out["updated_at"] = _iso_utc(out.get("updated_at"))
        return out

    def build_experiment_data(payload: ExperimentPayload, session: Session) -> dict[str, Any]:
        data = payload.model_dump()
        instance_id = data.pop("strategy_instance_id", None)
        if instance_id is not None:
            inst = session.get(StrategyInstance, instance_id)
            if not inst:
                raise HTTPException(status_code=404, detail="strategy instance not found")
            data.update(
                {
                    "strategy_key": inst.strategy_key,
                    "market_type": inst.market_type,
                    "symbol": inst.symbol,
                    "timeframe": inst.timeframe,
                    "initial_equity": inst.initial_equity,
                    "order_usdt": inst.order_usdt,
                    "fee_rate": inst.fee_rate,
                    "slippage_rate": inst.slippage_rate,
                    "fixed_params": inst.params,
                    "param_grid": {},
                }
            )
            data["description"] = (data.get("description") or "") + f"\nstrategy_instance_id={inst.id}"
        return data

    def ensure_backtest_data(session: Session, data: dict[str, Any], progress=None) -> None:
        if data.get("start_date") or data.get("end_date"):
            try:
                start_ts, end_ts, requested_start_ts, requested_end_ts, expected = _backtest_range_bounds(data)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            data.update(
                {
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "requested_start_ts": requested_start_ts,
                    "requested_end_ts": requested_end_ts,
                    "expected_candles": expected,
                    "candles_limit": None,
                }
            )
            batch_total = max(1, (expected + AUTO_FETCH_BATCH_CANDLES - 1) // AUTO_FETCH_BATCH_CANDLES)
            if progress:
                progress(
                    "checking_cache",
                    0,
                    expected,
                    f"检查本地缓存，预计 {expected} 根，最多分 {batch_total} 批拉取",
                )
            cached = app.state.market_data.list_candles(
                session,
                market_type=data["market_type"],
                symbol=data["symbol"],
                timeframe=data["timeframe"],
                start=start_ts,
                end=end_ts,
                completed_only=True,
            )
            if len(cached) >= expected:
                data["data_source"] = "cached"
                if progress:
                    progress("ready", expected, expected, "本地缓存已覆盖回测区间")
                return

            gateway = OKXGateway(current_settings(), "okx_demo", data["market_type"])
            seconds = timeframe_seconds(data["timeframe"])
            cursor = start_ts
            inserted_total = 0
            batch_index = 0
            try:
                while cursor <= end_ts:
                    if cursor > end_ts:
                        break
                    remaining = int((end_ts - cursor).total_seconds() // seconds) + 1
                    batch_limit = min(AUTO_FETCH_BATCH_CANDLES, max(3, remaining + 1))
                    batch_index += 1
                    completed_before_batch = min(
                        expected,
                        max(0, int((cursor - start_ts).total_seconds() // seconds)),
                    )
                    if progress:
                        progress(
                            "fetching",
                            completed_before_batch,
                            expected,
                            f"拉取第 {batch_index}/{batch_total} 批行情",
                        )
                    candles = gateway.fetch_candles(
                        symbol=data["symbol"],
                        timeframe=data["timeframe"],
                        limit=batch_limit,
                        since=cursor,
                    )
                    if not candles:
                        break
                    inserted_total += app.state.market_data.upsert_candles(
                        session,
                        market_type=data["market_type"],
                        symbol=data["symbol"],
                        timeframe=data["timeframe"],
                        candles=candles,
                        source="okx",
                    )
                    candle_times = [ensure_utc(candle.ts) for candle in candles if ensure_utc(candle.ts) >= cursor]
                    if not candle_times:
                        break
                    last_ts = max(candle_times)
                    next_cursor = last_ts + timedelta(seconds=seconds)
                    if next_cursor <= cursor:
                        break
                    cursor = next_cursor
                    completed_after_batch = min(
                        expected,
                        max(0, int((min(last_ts, end_ts) - start_ts).total_seconds() // seconds) + 1),
                    )
                    if progress:
                        progress(
                            "fetching",
                            completed_after_batch,
                            expected,
                            f"已拉取约 {completed_after_batch}/{expected} 根 K 线",
                        )
                    if last_ts >= end_ts:
                        break
            except Exception as exc:  # noqa: BLE001 - public exchange data can fail in ccxt/network layers
                raise HTTPException(status_code=502, detail=f"OKX candle auto-fetch failed: {exc}") from exc

            refreshed = app.state.market_data.list_candles(
                session,
                market_type=data["market_type"],
                symbol=data["symbol"],
                timeframe=data["timeframe"],
                start=start_ts,
                end=end_ts,
                completed_only=True,
            )
            if len(refreshed) < expected:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"OKX candle auto-fetch returned {len(refreshed)} completed candles for "
                        f"{data['market_type']} {data['symbol']} {data['timeframe']} "
                        f"from {_iso_utc(start_ts)} to {_iso_utc(end_ts)}; expected {expected}"
                    ),
            )
            data["data_source"] = "auto_okx"
            data["fetch_batches"] = batch_index
            data["fetch_batch_size"] = AUTO_FETCH_BATCH_CANDLES
            if progress:
                progress("ready", expected, expected, "行情准备完成，开始运行回测")
            _audit(
                session,
                "candles.auto_sync",
                "ok",
                f"auto-fetched {inserted_total} OKX candles before backtest",
                {
                    "market_type": data["market_type"],
                    "symbol": data["symbol"],
                    "timeframe": data["timeframe"],
                    "requested_start_ts": _iso_utc(requested_start_ts),
                    "requested_end_ts": _iso_utc(requested_end_ts),
                    "start_ts": _iso_utc(start_ts),
                    "end_ts": _iso_utc(end_ts),
                    "expected": expected,
                    "completed": len(refreshed),
                    "batches": batch_index,
                },
            )
            return

        target = max(3, min(int(data.get("candles_limit") or 300), 1000))
        fetch_limit = min(target + 1, 1000)
        required_completed = max(3, min(target, fetch_limit - 1))
        data["candles_limit"] = target
        cached = app.state.market_data.list_candles(
            session,
            market_type=data["market_type"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            limit=target,
            completed_only=True,
            latest=True,
        )
        if len(cached) >= required_completed:
            data["data_source"] = data.get("data_source") or "cached"
            return

        gateway = OKXGateway(current_settings(), "okx_demo", data["market_type"])
        try:
            candles = gateway.fetch_candles(
                symbol=data["symbol"],
                timeframe=data["timeframe"],
                limit=fetch_limit,
            )
        except Exception as exc:  # noqa: BLE001 - public exchange data can fail in ccxt/network layers
            raise HTTPException(status_code=502, detail=f"OKX candle auto-fetch failed: {exc}") from exc

        inserted = app.state.market_data.upsert_candles(
            session,
            market_type=data["market_type"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            candles=candles,
            source="okx",
        )
        refreshed = app.state.market_data.list_candles(
            session,
            market_type=data["market_type"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            limit=target,
            completed_only=True,
            latest=True,
        )
        if len(refreshed) < required_completed:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"OKX candle auto-fetch returned {len(refreshed)} completed candles for "
                    f"{data['market_type']} {data['symbol']} {data['timeframe']}; "
                    f"requested {required_completed}"
                ),
            )
        data["data_source"] = "auto_okx"
        _audit(
            session,
            "candles.auto_sync",
            "ok",
            f"auto-fetched {inserted} OKX candles before backtest",
            {
                "market_type": data["market_type"],
                "symbol": data["symbol"],
                "timeframe": data["timeframe"],
                "requested": target,
                "completed": len(refreshed),
            },
        )

    @app.get("/api/health")
    def health(session: Session = Depends(get_session)):
        session.execute(select(func.count()).select_from(StrategyTemplate)).scalar_one()
        return {"ok": True, "settings": current_settings().public_dict()}

    @app.get("/api/settings")
    def public_settings():
        return current_settings().public_dict()

    @app.get("/api/dashboard")
    def dashboard(session: Session = Depends(get_session)):
        best_runs = _serialize_runs(
            session.scalars(
                select(BacktestRun)
                .order_by(BacktestRun.total_return_pct.desc(), BacktestRun.sharpe.desc())
                .limit(8)
            ).all()
        )
        return {
            "settings": current_settings().public_dict(),
            "templates": session.scalar(select(func.count()).select_from(StrategyTemplate)) or 0,
            "instances": session.scalar(select(func.count()).select_from(StrategyInstance)) or 0,
            "experiments": session.scalar(select(func.count()).select_from(Experiment)) or 0,
            "backtests": session.scalar(select(func.count()).select_from(BacktestRun)) or 0,
            "trades": session.scalar(select(func.count()).select_from(Trade)) or 0,
            "candles": session.scalar(select(func.count()).select_from(Candle)) or 0,
            "best_runs": best_runs,
        }

    @app.get("/api/data/summary")
    def data_summary(session: Session = Depends(get_session)):
        rows = session.execute(
            select(
                Candle.market_type,
                Candle.symbol,
                Candle.timeframe,
                Candle.source,
                func.count(Candle.id),
                func.min(Candle.ts),
                func.max(Candle.ts),
                func.sum(Candle.completed.cast(Integer)),
            ).group_by(Candle.market_type, Candle.symbol, Candle.timeframe, Candle.source)
        ).all()
        return [
            {
                "market_type": row[0],
                "symbol": row[1],
                "timeframe": row[2],
                "source": row[3],
                "count": row[4],
                "start_ts": _iso_utc(row[5]),
                "end_ts": _iso_utc(row[6]),
                "completed": int(row[7] or 0),
            }
            for row in rows
        ]

    @app.get("/api/strategies")
    def strategies(session: Session = Depends(get_session)):
        rows = session.scalars(select(StrategyTemplate).order_by(StrategyTemplate.key)).all()
        if not rows:
            return strategy_templates()
        return [
            {
                "key": row.key,
                "name": row.name,
                "description": row.description,
                "param_schema": row.param_schema,
            }
            for row in rows
        ]

    @app.get("/api/instances")
    def list_instances(session: Session = Depends(get_session)):
        rows = session.scalars(select(StrategyInstance).order_by(StrategyInstance.created_at.desc())).all()
        return [_serialize_instance(row) for row in rows]

    @app.get("/api/instances/performance")
    def instance_performance(session: Session = Depends(get_session)):
        instances = session.scalars(select(StrategyInstance).order_by(StrategyInstance.created_at.desc())).all()
        if not instances:
            return {}
        instance_ids = [row.id for row in instances]
        trade_rows = session.scalars(
            select(Trade)
            .where(Trade.instance_id.in_(instance_ids))
            .where(Trade.broker_mode.in_(("okx_demo", "okx_live")))
            .order_by(Trade.ts)
        ).all()
        trades_by_instance: dict[int, list[Trade]] = {row.id: [] for row in instances}
        for trade in trade_rows:
            if trade.instance_id is not None:
                trades_by_instance.setdefault(trade.instance_id, []).append(trade)
        return {
            str(row.id): _instance_performance(row, trades_by_instance.get(row.id, []))
            for row in instances
        }

    @app.post("/api/instances")
    def create_instance(payload: InstancePayload, session: Session = Depends(get_session)):
        data = _normalize_instance_payload(payload.model_dump(), session)
        row = StrategyInstance(**data, status="enabled" if payload.enabled else "draft")
        session.add(row)
        session.flush()
        _audit(
            session,
            "instance.create",
            "ok",
            f"created strategy instance {row.name}",
            {"id": row.id, "account_id": row.account_id, "broker_mode": row.broker_mode},
        )
        session.commit()
        return _serialize_instance(row)

    @app.post("/api/instances/{instance_id}/test-order")
    def place_instance_test_order(
        instance_id: int,
        payload: InstanceOrderPayload,
        session: Session = Depends(get_session),
    ):
        side = payload.side.strip().lower()
        if side not in {"buy", "sell"}:
            raise HTTPException(status_code=400, detail="side must be buy or sell")
        row = session.get(StrategyInstance, instance_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy instance not found")
        if row.broker_mode not in {"okx_demo", "okx_live"}:
            raise HTTPException(status_code=400, detail="运行中心只支持 OKX Demo 和 OKX Live")
        account = _ensure_instance_account(session, row, row.broker_mode)
        if row.broker_mode == "okx_live":
            live_gate = LiveSafetyGate(current_settings()).validate(
                LiveTradeRequest(
                    broker_mode="okx_live",
                    instance_allow_live=row.allow_live,
                    confirmation=payload.confirmation,
                )
            )
            if not live_gate.allowed:
                raise HTTPException(status_code=400, detail="; ".join(live_gate.reasons))

        gateway = OKXGateway(_settings_for_account(account, current_settings()), row.broker_mode, row.market_type)
        price = _fetch_ticker_price(gateway, row.symbol)
        trade_rows = session.scalars(
            select(Trade)
            .where(Trade.instance_id == row.id)
            .where(Trade.broker_mode == row.broker_mode)
            .order_by(Trade.ts)
        ).all()
        net_position = _instance_net_position(list(trade_rows))
        amount = float(payload.amount or 0.0)
        if side == "buy" and amount <= 0:
            amount = payload.quote_usdt / price
        if side == "sell" and amount <= 0:
            amount = net_position
        if amount <= 0:
            raise HTTPException(status_code=400, detail="没有可卖出的实例持仓" if side == "sell" else "下单数量必须大于 0")
        if side == "sell":
            base_ccy = _symbol_base_ccy(row.symbol)
            free_balance = _fetch_free_balance(gateway, base_ccy)
            if free_balance <= 0:
                raise HTTPException(status_code=400, detail=f"{base_ccy} 可用余额不足")
            if amount > free_balance:
                if payload.amount is not None:
                    raise HTTPException(status_code=400, detail=f"{base_ccy} 可用余额不足，可用 {free_balance:.12f}")
                amount = free_balance * 0.999
            if amount <= 0:
                raise HTTPException(status_code=400, detail=f"{base_ccy} 可用余额不足")

        try:
            order = gateway.place_order(
                symbol=row.symbol,
                side=side,
                amount=amount,
                order_type="market",
                price=None,
                instance_allow_live=row.allow_live if row.broker_mode == "okx_live" else False,
                confirmation=payload.confirmation,
            )
        except Exception as exc:
            message = str(exc)
            session.add(
                Trade(
                    instance_id=row.id,
                    account_id=account.id,
                    ts=datetime.now(timezone.utc),
                    broker_mode=row.broker_mode,
                    market_type=row.market_type,
                    symbol=row.symbol,
                    side=side,
                    order_type="market",
                    amount=0.0,
                    price=price,
                    fee=0.0,
                    pnl=0.0,
                    meta={"reason": "manual_test", "status": "failed", "error": message, "attempted_amount": amount},
                )
            )
            _audit(
                session,
                "instance.test_order",
                "error",
                f"test {side} order failed for {row.name}",
                {"id": row.id, "account_id": account.id, "broker_mode": row.broker_mode, "error": message},
            )
            session.commit()
            raise HTTPException(status_code=502, detail=f"OKX 官方 API 不可用或下单失败: {message}") from exc

        notional = amount * price
        fee = notional * float(row.fee_rate or 0.0)
        avg_entry = _instance_average_entry(list(trade_rows))
        pnl = (price - avg_entry) * min(amount, net_position) - fee if side == "sell" and avg_entry > 0 else 0.0
        order_id = _extract_order_id(order)
        trade = Trade(
            instance_id=row.id,
            account_id=account.id,
            ts=datetime.now(timezone.utc),
            broker_mode=row.broker_mode,
            market_type=row.market_type,
            symbol=row.symbol,
            side=side,
            order_type="market",
            amount=amount,
            price=price,
            fee=fee,
            pnl=pnl,
            external_order_id=order_id,
            meta={
                "reason": "manual_test",
                "execution": "okx",
                "order_id": order_id,
                "order_response": order,
            },
        )
        session.add(trade)
        _audit(
            session,
            "instance.test_order",
            "ok",
            f"test {side} order placed for {row.name}",
            {"id": row.id, "account_id": account.id, "broker_mode": row.broker_mode, "order_id": order_id},
        )
        session.commit()
        return _serialize_trade(trade, session=session)

    @app.get("/api/instances/{instance_id}/trades")
    def list_instance_trades(
        instance_id: int,
        limit: int = 200,
        session: Session = Depends(get_session),
    ):
        row = session.get(StrategyInstance, instance_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy instance not found")
        rows = session.scalars(
            select(Trade)
            .where(Trade.instance_id == instance_id)
            .order_by(Trade.ts.desc())
            .limit(max(1, min(limit, 1000)))
        ).all()
        return [_serialize_trade(trade, session=session) for trade in rows]

    @app.patch("/api/instances/{instance_id}")
    def update_instance(instance_id: int, payload: InstancePayload, session: Session = Depends(get_session)):
        row = session.get(StrategyInstance, instance_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy instance not found")
        data = _normalize_instance_payload(payload.model_dump(), session)
        for key, value in data.items():
            setattr(row, key, value)
        row.status = "enabled" if payload.enabled else row.status
        _audit(
            session,
            "instance.update",
            "ok",
            f"updated strategy instance {row.name}",
            {"id": row.id, "account_id": row.account_id, "broker_mode": row.broker_mode},
        )
        session.commit()
        return _serialize_instance(row)

    @app.delete("/api/instances/{instance_id}")
    def delete_instance(instance_id: int, session: Session = Depends(get_session)):
        row = session.get(StrategyInstance, instance_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy instance not found")
        app.state.runner_manager.stop_instance(instance_id)
        name = row.name
        session.delete(row)
        _audit(session, "instance.delete", "ok", f"deleted strategy instance {name}", {"id": instance_id})
        session.commit()
        return {"ok": True}

    @app.post("/api/instances/{instance_id}/status")
    def update_instance_status(instance_id: int, payload: InstanceStatusPayload, session: Session = Depends(get_session)):
        if payload.status not in {
            "draft",
            "okx_demo_running",
            "okx_live_running",
            "paused",
            "stopped",
            "reset",
            "enabled",
        }:
            raise HTTPException(status_code=400, detail="invalid instance status")
        row = session.get(StrategyInstance, instance_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy instance not found")
        if payload.status == "okx_live_running":
            account = _ensure_instance_account(session, row, "okx_live")
            live_gate = LiveSafetyGate(current_settings()).validate(
                LiveTradeRequest(
                    broker_mode="okx_live",
                    instance_allow_live=row.allow_live,
                    confirmation=payload.confirmation,
                )
            )
            if not live_gate.allowed:
                raise HTTPException(status_code=400, detail="; ".join(live_gate.reasons))
            row.broker_mode = "okx_live"
            row.account_id = account.id
        elif payload.status == "okx_demo_running":
            account = _ensure_instance_account(session, row, "okx_demo")
            row.broker_mode = "okx_demo"
            row.account_id = account.id
        row.status = payload.status
        _audit(
            session,
            "instance.status",
            "ok",
            f"instance {row.name} -> {payload.status}",
            {"id": row.id, "account_id": row.account_id, "broker_mode": row.broker_mode},
        )
        session.commit()

        # Start/stop runner based on status
        rm = app.state.runner_manager
        if payload.status in {"okx_demo_running", "okx_live_running"}:
            rm.start_instance(instance_id)
        elif payload.status in {"paused", "stopped", "reset", "draft", "enabled"}:
            rm.stop_instance(instance_id)

        return _serialize_instance(row)

    @app.post("/api/candles/seed")
    def seed_candles(
        market_type: str = "spot",
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        count: int = 360,
        session: Session = Depends(get_session),
    ):
        inserted = app.state.market_data.seed_sample(
            session,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            count=max(3, min(count, 5000)),
        )
        _audit(session, "candles.seed", "ok", f"seeded {inserted} sample candles", {"symbol": symbol})
        session.commit()
        return {"inserted": inserted}

    @app.post("/api/candles/sync")
    def sync_candles(payload: CandleSyncPayload, session: Session = Depends(get_session)):
        if payload.source == "sample":
            inserted = app.state.market_data.seed_sample(
                session,
                market_type=payload.market_type,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                count=max(3, min(payload.limit, 5000)),
            )
            source = "sample"
        elif payload.source == "okx":
            gateway = OKXGateway(current_settings(), "okx_demo", payload.market_type)
            try:
                candles = gateway.fetch_candles(
                    symbol=payload.symbol,
                    timeframe=payload.timeframe,
                    limit=max(3, min(payload.limit, 1000)),
                )
            except Exception as exc:  # noqa: BLE001 - external exchange clients raise broad errors
                raise HTTPException(status_code=502, detail=f"OKX candle sync failed: {exc}") from exc
            inserted = app.state.market_data.upsert_candles(
                session,
                market_type=payload.market_type,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                candles=candles,
                source="okx",
            )
            source = "okx"
        else:
            raise HTTPException(status_code=400, detail="source must be okx or sample")
        _audit(session, "candles.sync", "ok", f"synced {inserted} {source} candles", payload.model_dump())
        session.commit()
        return {"inserted": inserted, "source": source}

    @app.get("/api/candles")
    def candles(
        market_type: str = "spot",
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 200,
        session: Session = Depends(get_session),
    ):
        rows = app.state.market_data.list_candles(
            session,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            limit=max(1, min(limit, 2000)),
            completed_only=True,
        )
        return [
            {
                "time": _iso_utc(row.ts),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "completed": row.completed,
            }
            for row in rows
        ]

    @app.post("/api/backtests/run")
    def run_backtest(payload: BacktestPayload, session: Session = Depends(get_session)):
        data = {
            "name": "single backtest",
            "strategy_key": payload.strategy_key,
            "market_type": payload.market_type,
            "symbol": payload.symbol,
            "timeframe": payload.timeframe,
            "initial_equity": payload.initial_equity,
            "order_usdt": payload.order_usdt,
            "fee_rate": payload.fee_rate,
            "slippage_rate": payload.slippage_rate,
            "fixed_params": payload.strategy_params,
            "param_grid": {},
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "candles_limit": payload.candles_limit,
        }
        ensure_backtest_data(session, data)
        spec = ExperimentSpec(**data)
        try:
            experiment, runs = app.state.experiments.create_and_run(session, spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _audit(session, "backtest.run", "ok", "created single-run backtest", {"experiment_id": experiment.id})
        session.commit()
        return {"experiment": _serialize_experiment(experiment), "runs": _serialize_runs(runs)}

    def run_experiment_job(job_id: str, payload_data: dict[str, Any]) -> None:
        def progress(stage: str, current: int, total: int, message: str) -> None:
            percent = round((current / total) * 100, 2) if total else None
            set_job(
                job_id,
                status="running",
                progress={
                    "stage": stage,
                    "current": current,
                    "total": total,
                    "percent": percent,
                    "message": message,
                },
            )

        try:
            payload = ExperimentPayload(**payload_data)
            with database.session() as session:
                set_job(job_id, status="running", progress={"stage": "queued", "message": "开始创建实验"})
                data = build_experiment_data(payload, session)
                ensure_backtest_data(session, data, progress=progress)
                progress("backtesting", data.get("expected_candles") or 0, data.get("expected_candles") or 0, "运行策略回测")
                experiment, runs = app.state.experiments.create_and_run(session, ExperimentSpec(**data))
                _audit(session, "experiment.create", "ok", f"created experiment {experiment.name}", {"runs": len(runs)})
                session.commit()
                set_job(
                    job_id,
                    status="completed",
                    progress={
                        "stage": "completed",
                        "current": data.get("expected_candles") or len(runs),
                        "total": data.get("expected_candles") or len(runs),
                        "percent": 100,
                        "message": "实验完成",
                    },
                    result={"experiment": _serialize_experiment(experiment), "runs": _serialize_runs(runs)},
                )
        except HTTPException as exc:
            set_job(
                job_id,
                status="failed",
                error=str(exc.detail),
                progress={"stage": "failed", "message": str(exc.detail)},
            )
        except Exception as exc:  # noqa: BLE001 - background job must report errors to UI
            set_job(
                job_id,
                status="failed",
                error=str(exc),
                progress={"stage": "failed", "message": str(exc)},
            )

    @app.post("/api/experiments/jobs")
    def create_experiment_job(payload: ExperimentPayload):
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        job = {
            "id": job_id,
            "status": "queued",
            "progress": {"stage": "queued", "message": "排队中"},
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with app.state.experiment_jobs_lock:
            app.state.experiment_jobs[job_id] = job
        thread = threading.Thread(target=run_experiment_job, args=(job_id, payload.model_dump()), daemon=True)
        thread.start()
        return serialize_job(job)

    @app.get("/api/experiments/jobs/{job_id}")
    def get_experiment_job(job_id: str):
        with app.state.experiment_jobs_lock:
            job = app.state.experiment_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="experiment job not found")
            return serialize_job(job)

    @app.post("/api/experiments")
    def create_experiment(payload: ExperimentPayload, session: Session = Depends(get_session)):
        data = build_experiment_data(payload, session)
        ensure_backtest_data(session, data)
        try:
            experiment, runs = app.state.experiments.create_and_run(session, ExperimentSpec(**data))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _audit(session, "experiment.create", "ok", f"created experiment {experiment.name}", {"runs": len(runs)})
        session.commit()
        return {"experiment": _serialize_experiment(experiment), "runs": _serialize_runs(runs)}

    @app.get("/api/experiments")
    def list_experiments(session: Session = Depends(get_session)):
        experiments = session.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(100)).all()
        return [_serialize_experiment(row) for row in experiments]

    @app.delete("/api/experiments/{experiment_id}")
    def delete_experiment(experiment_id: int, session: Session = Depends(get_session)):
        row = session.get(Experiment, experiment_id)
        if not row:
            raise HTTPException(status_code=404, detail="experiment not found")
        # Delete associated runs and their equity points/trades
        runs = session.scalars(select(BacktestRun).where(BacktestRun.experiment_id == experiment_id)).all()
        for run in runs:
            session.query(EquityPoint).where(EquityPoint.run_id == run.id).delete()
            session.query(Trade).where(Trade.run_id == run.id).delete()
            session.delete(run)
        name = row.name
        session.delete(row)
        _audit(session, "experiment.delete", "ok", f"deleted experiment {name}", {"id": experiment_id, "runs": len(runs)})
        session.commit()
        return {"ok": True}

    @app.get("/api/experiments/{experiment_id}/runs")
    def experiment_runs(experiment_id: int, session: Session = Depends(get_session)):
        rows = session.scalars(
            select(BacktestRun)
            .where(BacktestRun.experiment_id == experiment_id)
            .order_by(BacktestRun.total_return_pct.desc(), BacktestRun.sharpe.desc())
        ).all()
        return _serialize_runs(rows)

    @app.get("/api/runs/leaderboard")
    def runs_leaderboard(session: Session = Depends(get_session)):
        top = session.scalars(
            select(BacktestRun)
            .order_by(BacktestRun.total_return_pct.desc(), BacktestRun.max_drawdown_pct.desc(), BacktestRun.sharpe.desc())
            .limit(10)
        ).all()
        recent_ids = {r.id for r in top}
        recent = session.scalars(
            select(BacktestRun)
            .order_by(BacktestRun.created_at.desc())
            .limit(5)
        ).all()
        recent_filtered = [r for r in recent if r.id not in recent_ids][:3]
        return {
            "top": _serialize_runs(top),
            "recent": _serialize_runs(recent_filtered),
        }

    @app.get("/api/runs")
    def runs(
        page: int = 1,
        page_size: int = 20,
        session: Session = Depends(get_session),
    ):
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        total = session.scalar(select(func.count()).select_from(BacktestRun)) or 0
        rows = session.scalars(
            select(BacktestRun)
            .order_by(BacktestRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {"items": _serialize_runs(rows), "total": total, "page": page, "page_size": page_size}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: int, session: Session = Depends(get_session)):
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        equity = session.scalars(select(EquityPoint).where(EquityPoint.run_id == run_id).order_by(EquityPoint.ts)).all()
        trades = session.scalars(select(Trade).where(Trade.run_id == run_id).order_by(Trade.ts)).all()
        experiment = session.get(Experiment, run.experiment_id) if run.experiment_id else None
        candle_rows = app.state.market_data.list_candles(
            session,
            market_type=run.market_type,
            symbol=run.symbol,
            timeframe=run.timeframe,
            start=run.start_ts,
            end=run.end_ts,
            completed_only=True,
        )
        equity_points = [
            {"time": _iso_utc(p.ts), "equity": p.equity, "cash": p.cash, "position_value": p.position_value}
            for p in equity
        ]
        return {
            "run": _serialize_run(run, experiment),
            "experiment": _serialize_experiment(experiment) if experiment else None,
            "candles": [
                {
                    "time": _iso_utc(c.ts),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "completed": c.completed,
                }
                for c in _downsample(candle_rows, 360)
            ],
            "equity_curve": _downsample(equity_points, 360),
            "benchmark_curve": _benchmark_curve(candle_rows, run.initial_equity),
            "drawdown_curve": _drawdown_curve(equity_points),
            "trades": [_serialize_trade(row, session=session) for row in trades],
        }

    @app.get("/api/trades")
    def list_trades(
        run_id: int | None = None,
        instance_id: int | None = None,
        account_id: int | None = None,
        source: str | None = None,
        limit: int = 200,
        session: Session = Depends(get_session),
    ):
        stmt = select(Trade).order_by(Trade.ts.desc())
        if run_id is not None:
            stmt = stmt.where(Trade.run_id == run_id)
        if instance_id is not None:
            stmt = stmt.where(Trade.instance_id == instance_id)
        if account_id is not None:
            stmt = stmt.where(Trade.account_id == account_id)
        if source and source != "all":
            if source not in {"backtest", "okx_demo", "okx_live"}:
                raise HTTPException(status_code=400, detail="invalid trade source")
            stmt = stmt.where(Trade.broker_mode == source)
        rows = session.scalars(stmt.limit(max(1, min(limit, 1000)))).all()
        return [_serialize_trade(row, session=session) for row in rows]

    @app.get("/api/trades/{trade_id}")
    def get_trade_detail(trade_id: int, session: Session = Depends(get_session)):
        row = session.get(Trade, trade_id)
        if not row:
            raise HTTPException(status_code=404, detail="trade not found")
        payload = _serialize_trade(row, session=session)
        instance = session.get(StrategyInstance, row.instance_id) if row.instance_id else None
        account = session.get(AccountConfig, row.account_id) if row.account_id else None
        payload["instance"] = _serialize_instance_brief(instance) if instance else None
        payload["account"] = _serialize_account_brief(account) if account else None
        order_id = row.external_order_id or (row.meta or {}).get("order_id")
        if account and order_id and row.broker_mode in {"okx_demo", "okx_live"}:
            try:
                gateway = OKXGateway(_settings_for_account(account), row.broker_mode, row.market_type)
                payload["okx_order"] = gateway.fetch_order_details(
                    inst_id=okx_inst_id(row.symbol, row.market_type),
                    order_id=str(order_id),
                )
            except Exception as exc:
                payload["okx_order_error"] = f"OKX 官方 API 不可用: {exc}"
        return payload

    @app.post("/api/runs/{run_id}/promote")
    def promote_run(run_id: int, payload: PromotePayload, session: Session = Depends(get_session)):
        if payload.status not in {"none", "paper_candidate", "live_candidate", "rejected"}:
            raise HTTPException(status_code=400, detail="invalid promotion status")
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        run.promotion_status = payload.status
        _audit(session, "run.promote", "ok", f"run {run_id} promoted to {payload.status}", {})
        session.commit()
        return _serialize_run(run)

    @app.post("/api/live/validate")
    def validate_live(payload: LiveValidationPayload):
        result = LiveSafetyGate(current_settings()).validate(
            LiveTradeRequest(
                broker_mode=payload.broker_mode,
                instance_allow_live=payload.instance_allow_live,
                confirmation=payload.confirmation,
            )
        )
        return {"allowed": result.allowed, "reasons": result.reasons}

    @app.get("/api/settings/credentials")
    def get_credentials():
        s = current_settings()

        def mask(val):
            if not val:
                return ""
            return "*" * len(val)

        return {
            "okx_api_key": s.okx_api_key or "",
            "okx_api_key_configured": bool(s.okx_api_key),
            "okx_api_secret_configured": bool(s.okx_api_secret),
            "okx_api_password_configured": bool(s.okx_api_password),
            "okx_api_secret_masked": mask(s.okx_api_secret),
            "okx_api_password_masked": mask(s.okx_api_password),
        }

    @app.post("/api/settings/credentials")
    def update_credentials(payload: CredentialPayload, session: Session = Depends(get_session)):
        active = current_settings()
        app.state.settings = replace(
            active,
            okx_api_key=payload.okx_api_key or active.okx_api_key,
            okx_api_secret=payload.okx_api_secret or active.okx_api_secret,
            okx_api_password=payload.okx_api_password or active.okx_api_password,
        )
        _save_settings_to_db(app.state.database, current_settings())
        app.state.runner_manager.update_settings(current_settings())
        _audit(session, "credentials.update", "ok", "credentials updated", {})
        return current_settings().public_dict()

    @app.post("/api/settings/okx/test")
    def test_okx_connection():
        try:
            gateway = OKXGateway(current_settings(), "okx_demo", "spot")
            candles = gateway.fetch_candles(symbol="BTC/USDT", timeframe="1m", limit=5)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "candles": len(candles), "message": "OKX public market data reachable"}

    @app.post("/api/settings/live")
    def validate_live_settings(payload: LiveSettingsPayload):
        active = current_settings()
        result = LiveSafetyGate(active).validate(
            LiveTradeRequest(
                broker_mode="okx_live",
                instance_allow_live=True,
                confirmation=payload.confirmation,
            )
        )
        return {
            "allowed": result.allowed,
            "reasons": result.reasons,
            "settings": active.public_dict(),
        }

    # Account management endpoints
    @app.get("/api/accounts")
    def list_accounts(session: Session = Depends(get_session)):
        rows = session.scalars(select(AccountConfig).order_by(AccountConfig.created_at.desc())).all()
        return [_serialize_account(row) for row in rows]

    @app.get("/api/accounts/summary")
    def accounts_summary(session: Session = Depends(get_session)):
        rows = session.scalars(select(AccountConfig).order_by(AccountConfig.created_at.desc())).all()
        return [_build_account_summary(row, session) for row in rows]

    @app.post("/api/accounts")
    def create_account(payload: AccountPayload, session: Session = Depends(get_session)):
        row = AccountConfig(**payload.model_dump())
        session.add(row)
        session.flush()
        _audit(session, "account.create", "ok", f"created account {row.name}", {"id": row.id})
        session.commit()
        return _serialize_account(row)

    @app.put("/api/accounts/{account_id}")
    def update_account(account_id: int, payload: AccountUpdatePayload, session: Session = Depends(get_session)):
        row = session.get(AccountConfig, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key in {"api_secret", "passphrase"} and not value:
                continue
            if value is None:
                continue
            setattr(row, key, value)
        _audit(session, "account.update", "ok", f"updated account {row.name}", {"id": row.id})
        session.commit()
        return _serialize_account(row)

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int, session: Session = Depends(get_session)):
        row = session.get(AccountConfig, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        name = row.name
        session.delete(row)
        _audit(session, "account.delete", "ok", f"deleted account {name}", {"id": account_id})
        session.commit()
        return {"ok": True}

    @app.get("/api/accounts/{account_id}/balance")
    def get_account_balance(account_id: int, session: Session = Depends(get_session)):
        row = session.get(AccountConfig, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        try:
            gateway = OKXGateway(_settings_for_account(row), row.account_type, "spot")
            data = gateway.fetch_account_balance()
            if data.get("code") != "0":
                return {"ok": False, "error": _okx_error_message(data), "code": data.get("code")}
            balances, total_eq = _parse_okx_account_balance(data)
            return {
                "ok": True,
                "balances": balances,
                "total_eq": total_eq,
                "message": "" if balances else "OKX 官方 API 返回空余额",
            }
        except Exception as e:
            return {"ok": False, "error": f"OKX 官方 API 不可用: {e}"}

    @app.get("/api/accounts/{account_id}/positions")
    def get_account_positions(account_id: int, session: Session = Depends(get_session)):
        row = session.get(AccountConfig, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        try:
            gateway = OKXGateway(_settings_for_account(row), row.account_type, "spot")
            data = gateway.fetch_positions()
            if data.get("code") != "0":
                return {"ok": False, "error": _okx_error_message(data), "code": data.get("code")}
            positions = data.get("data") if isinstance(data.get("data"), list) else []
            return {
                "ok": True,
                "positions": positions,
                "message": "" if positions else "OKX 官方 API 返回空持仓",
            }
        except Exception as e:
            return {"ok": False, "error": f"OKX 官方 API 不可用: {e}"}

    @app.post("/api/accounts/{account_id}/demo-balance-adjust")
    def adjust_demo_balance(
        account_id: int,
        payload: DemoBalanceAdjustPayload,
        session: Session = Depends(get_session),
    ):
        row = session.get(AccountConfig, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        if row.account_type != "okx_demo":
            raise HTTPException(status_code=400, detail="demo balance adjustment is only available for OKX Demo")
        adjustment_type, ccy, amt = _validate_demo_balance_adjustment(payload)
        try:
            gateway = OKXGateway(_settings_for_account(row), row.account_type, "spot")
            data = gateway.adjust_demo_balance(
                adjustment_type=adjustment_type,
                adjustments=[{"ccy": ccy, "amt": amt}],
            )
            if data.get("code") != "0":
                return {"ok": False, "error": _okx_error_message(data), "code": data.get("code"), "data": data.get("data")}
            _audit(
                session,
                "account.demo_balance_adjust",
                "ok",
                f"adjusted OKX Demo balance for {row.name}",
                {"id": row.id, "type": adjustment_type, "ccy": ccy, "amt": amt},
            )
            session.commit()
            return {"ok": True, "result": data}
        except Exception as e:
            return {"ok": False, "error": f"OKX 官方 API 不可用: {e}"}

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(frontend_dist / "index.html")

        _ALLOWED_EXTENSIONS = {".html", ".js", ".css", ".json", ".svg", ".png", ".ico", ".woff2"}

        @app.get("/{path:path}")
        def spa(path: str):
            candidate = frontend_dist / path
            ext = candidate.suffix.lower()
            if candidate.exists() and candidate.is_file() and ext in _ALLOWED_EXTENSIONS:
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


def _audit(session: Session, action: str, status: str, message: str, meta: dict[str, Any]) -> None:
    session.add(AuditEvent(action=action, status=status, message=message, meta=meta))


def _serialize_instance(row: StrategyInstance) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "strategy_key": row.strategy_key,
        "account_id": row.account_id,
        "enabled": row.enabled,
        "broker_mode": row.broker_mode,
        "market_type": row.market_type,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "initial_equity": row.initial_equity,
        "order_usdt": row.order_usdt,
        "fee_rate": row.fee_rate,
        "slippage_rate": row.slippage_rate,
        "allow_live": row.allow_live,
        "params": row.params,
        "status": row.status,
        "created_at": _iso_utc(row.created_at),
    }


def _serialize_instance_brief(row: StrategyInstance) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "strategy_key": row.strategy_key,
        "broker_mode": row.broker_mode,
        "status": row.status,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "account_id": row.account_id,
    }


def _instance_performance(instance: StrategyInstance, trades: list[Trade]) -> dict[str, Any]:
    executed_trades = _executed_trades(trades)
    failed_count = len(trades) - len(executed_trades)
    realized_pnl = sum(float(row.pnl or 0.0) for row in executed_trades)
    fee_paid = sum(float(row.fee or 0.0) for row in executed_trades)
    wins = sum(1 for row in executed_trades if float(row.pnl or 0.0) > 0)
    losses = sum(1 for row in executed_trades if float(row.pnl or 0.0) < 0)
    closed = wins + losses
    buy_qty = sum(float(row.amount or 0.0) for row in executed_trades if row.side == "buy")
    sell_qty = sum(float(row.amount or 0.0) for row in executed_trades if row.side == "sell")
    turnover = sum(float(row.amount or 0.0) * float(row.price or 0.0) for row in executed_trades)
    last_trade = executed_trades[-1] if executed_trades else None
    last_order = trades[-1] if trades else None
    last_failed = next((row for row in reversed(trades) if (row.meta or {}).get("status") == "failed"), None)
    broker_modes = sorted({row.broker_mode for row in executed_trades})
    initial_equity = float(instance.initial_equity or 0.0)
    return {
        "instance_id": instance.id,
        "account_id": instance.account_id,
        "trades_count": len(executed_trades),
        "failed_trades_count": failed_count,
        "buy_count": sum(1 for row in executed_trades if row.side == "buy"),
        "sell_count": sum(1 for row in executed_trades if row.side == "sell"),
        "realized_pnl": realized_pnl,
        "return_pct": (realized_pnl / initial_equity * 100) if initial_equity > 0 else 0.0,
        "win_rate_pct": (wins / closed * 100) if closed else 0.0,
        "wins_count": wins,
        "losses_count": losses,
        "fee_paid": fee_paid,
        "turnover": turnover,
        "net_position": buy_qty - sell_qty,
        "last_trade_ts": _iso_utc(last_trade.ts) if last_trade else None,
        "last_trade_price": last_trade.price if last_trade else None,
        "last_order_ts": _iso_utc(last_order.ts) if last_order else None,
        "last_order_status": _trade_order_status(last_order) if last_order else None,
        "last_failed_order_ts": _iso_utc(last_failed.ts) if last_failed else None,
        "last_failed_order_status": _trade_order_status(last_failed) if last_failed else None,
        "broker_modes": broker_modes,
    }


def _iso_utc(dt):
    """ISO 8601 string with UTC suffix. SQLite returns naive datetimes."""
    if dt is None:
        return None
    s = dt.isoformat()
    if not s.endswith(("+00:00", "Z")):
        s += "+00:00"
    return s


def _serialize_experiment(row: Experiment) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "request": row.request,
        "created_at": _iso_utc(row.created_at),
    }


def _serialize_runs(rows) -> list[dict[str, Any]]:
    return [_serialize_run(row) for row in rows]


def _serialize_run(row: BacktestRun, experiment: Experiment | None = None) -> dict[str, Any]:
    experiment = experiment or getattr(row, "experiment", None)
    request = experiment.request if experiment else {}
    return {
        "id": row.id,
        "experiment_id": row.experiment_id,
        "experiment_name": experiment.name if experiment else "",
        "strategy_key": row.strategy_key,
        "strategy_params": row.strategy_params,
        "market_type": row.market_type,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "initial_equity": row.initial_equity,
        "final_equity": row.final_equity,
        "total_return_pct": row.total_return_pct,
        "annual_return_pct": row.annual_return_pct,
        "max_drawdown_pct": row.max_drawdown_pct,
        "sharpe": row.sharpe,
        "calmar": row.calmar,
        "win_rate": row.win_rate,
        "profit_factor": row.profit_factor,
        "trades_count": row.trades_count,
        "fee_paid": row.fee_paid,
        "data_source": request.get("data_source", "cached"),
        "candles_count": request.get("candles_count"),
        "expected_candles": request.get("expected_candles"),
        "requested_start_ts": request.get("requested_start_ts"),
        "requested_end_ts": request.get("requested_end_ts"),
        "start_ts": _iso_utc(row.start_ts),
        "end_ts": _iso_utc(row.end_ts),
        "promotion_status": row.promotion_status,
        "code_version": row.code_version,
        "created_at": _iso_utc(row.created_at),
    }


def _serialize_trade(row: Trade, session: Session | None = None) -> dict[str, Any]:
    run = session.get(BacktestRun, row.run_id) if session is not None and row.run_id else None
    experiment = session.get(Experiment, run.experiment_id) if session is not None and run and run.experiment_id else None
    instance = session.get(StrategyInstance, row.instance_id) if session is not None and row.instance_id else None
    account = session.get(AccountConfig, row.account_id) if session is not None and row.account_id else None
    return {
        "id": row.id,
        "ts": _iso_utc(row.ts),
        "broker_mode": row.broker_mode,
        "market_type": row.market_type,
        "symbol": row.symbol,
        "side": row.side,
        "order_type": row.order_type,
        "amount": row.amount,
        "price": row.price,
        "fee": row.fee,
        "pnl": row.pnl,
        "external_order_id": row.external_order_id,
        "meta": row.meta,
        "run_id": row.run_id,
        "instance_id": row.instance_id,
        "instance_name": instance.name if instance else "",
        "account_id": row.account_id,
        "account_name": account.name if account else "",
        "account_type": account.account_type if account else "",
        "experiment_name": experiment.name if experiment else "",
        "strategy_key": instance.strategy_key if instance else run.strategy_key if run else "",
        "order_status": _trade_order_status(row),
    }


def _trade_order_status(row: Trade) -> dict[str, Any]:
    meta = row.meta or {}
    if meta.get("status") == "failed":
        details = _parse_order_error(meta.get("error"))
        return {
            "state": "failed",
            "label": "下单失败",
            "code": details["code"],
            "sub_code": details["sub_code"],
            "reason": details["message"],
            "exchange_message": details["exchange_message"],
            "error": details["raw"],
            "attempted_amount": meta.get("attempted_amount"),
        }

    order_id = row.external_order_id or meta.get("order_id")
    if row.broker_mode in {"okx_demo", "okx_live"}:
        order_response = meta.get("order_response") if isinstance(meta, dict) else None
        okx_row = None
        if isinstance(order_response, dict):
            info = order_response.get("info")
            data = info.get("data") if isinstance(info, dict) else None
            okx_row = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        response_msg = str(okx_row.get("sMsg") or "") if okx_row else ""
        return {
            "state": "submitted" if order_id else "recorded",
            "label": "已提交" if order_id else "已记录",
            "code": str(okx_row.get("sCode")) if okx_row and okx_row.get("sCode") not in (None, "") else None,
            "reason": response_msg or None,
            "order_id": str(order_id) if order_id else None,
            "attempted_amount": row.amount,
        }

    return {
        "state": "recorded",
        "label": "已记录",
        "code": None,
        "reason": None,
        "order_id": str(order_id) if order_id else None,
        "attempted_amount": row.amount,
    }


def _downsample(items: list[Any], limit: int) -> list[Any]:
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(index * step)] for index in range(limit)]


def _benchmark_curve(candles, initial_equity: float) -> list[dict[str, Any]]:
    completed = [c for c in candles if c.completed]
    if not completed:
        return []
    base = completed[0].close or 1.0
    points = [{"time": _iso_utc(c.ts), "equity": initial_equity * (c.close / base)} for c in completed]
    return _downsample(points, 360)


def _drawdown_curve(equity_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = None
    out = []
    for point in equity_points:
        equity = float(point["equity"])
        peak = equity if peak is None else max(peak, equity)
        drawdown = (equity / peak - 1) * 100 if peak else 0.0
        out.append({"time": point["time"], "drawdown": drawdown})
    return _downsample(out, 360)


def _serialize_account(row: AccountConfig) -> dict[str, Any]:
    def mask(val: str) -> str:
        if not val:
            return ""
        return "*" * len(val)

    return {
        "id": row.id,
        "name": row.name,
        "account_type": row.account_type,
        "api_key": row.api_key,
        "api_key_masked": row.api_key[:8] + "..." if len(row.api_key) > 8 else row.api_key,
        "api_secret_masked": mask(row.api_secret),
        "passphrase_masked": mask(row.passphrase),
        "is_active": row.is_active,
        "created_at": _iso_utc(row.created_at),
    }


def _serialize_account_brief(row: AccountConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "account_type": row.account_type,
        "api_key_masked": row.api_key[:8] + "..." if len(row.api_key) > 8 else row.api_key,
        "is_active": row.is_active,
        "created_at": _iso_utc(row.created_at),
    }
