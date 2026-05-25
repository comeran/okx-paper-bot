"""Background strategy runner for OKX demo/live execution."""
from __future__ import annotations

import logging
import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from okx_paper_bot.brokers import OKXGateway, Fill
from okx_paper_bot.config import AppSettings
from okx_paper_bot.market import CandleData, MarketDataService, timeframe_seconds
from okx_paper_bot.persistence.db import Database
from okx_paper_bot.persistence.models import AccountConfig, AuditEvent, BacktestRun, EquityPoint, StrategyInstance, Trade
from okx_paper_bot.strategies import StrategyContext, create_strategy

logger = logging.getLogger(__name__)

POLL_INTERVAL = 8  # seconds between each price check
CACHE_FLUSH_INTERVAL = 300  # seconds between database writes (5 minutes)
FATAL_ORDER_ERROR_MARKERS = (
    '"code":"50101"',
    '"code":"50111"',
    '"code":"50119"',
    "APIKey does not match current environment",
    "Invalid OK-ACCESS-KEY",
    "API key doesn't exist",
)


def _is_fatal_order_error(message: str) -> bool:
    return any(marker in message for marker in FATAL_ORDER_ERROR_MARKERS)


def _order_id(order: Any) -> str | None:
    if not isinstance(order, dict):
        return None
    value = order.get("id") or order.get("orderId")
    if value:
        return str(value)
    info = order.get("info")
    if isinstance(info, dict):
        rows = info.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            value = rows[0].get("ordId")
            return str(value) if value else None
    return None


def _settings_for_account(row: AccountConfig, base: AppSettings | None = None) -> AppSettings:
    active = base or AppSettings()
    return replace(
        active,
        okx_api_key=row.api_key,
        okx_api_secret=row.api_secret,
        okx_api_password=row.passphrase,
    )


def _symbol_base_ccy(symbol: str) -> str:
    normalized = symbol.split(":", 1)[0].replace("-", "/")
    return normalized.split("/", 1)[0].upper()


def _free_balance_from_okx(data: dict[str, Any], ccy: str) -> float:
    rows = data.get("data") if isinstance(data, dict) else None
    account = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    details = account.get("details") if isinstance(account, dict) else []
    if not isinstance(details, list):
        return 0.0
    for detail in details:
        if not isinstance(detail, dict) or str(detail.get("ccy") or "").upper() != ccy.upper():
            continue
        value = detail.get("availBal") or detail.get("availEq") or detail.get("cashBal") or "0"
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


class StrategyRunner:
    """Runs a single strategy instance with real-time polling."""

    def __init__(
        self,
        instance_id: int,
        settings: AppSettings,
        database: Database,
        market_data: MarketDataService,
    ):
        self.instance_id = instance_id
        self.settings = settings
        self.database = database
        self.market_data = market_data
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {}
        self._live_run_id: int | None = None
        self._last_candle_ts: datetime | None = None
        self._last_signal_ts: datetime | None = None
        self._last_signal_key: tuple[str, str] | None = None
        # Candle buffer for batch writes
        self._candle_buffer: list[tuple[str, str, str, list[CandleData]]] = []
        self._last_flush_ts: float = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            if inst:
                self._state = {
                    "cash": inst.initial_equity,
                    "position_size": 0.0,
                    "avg_entry_price": 0.0,
                    "last_price": 0.0,
                }
                run = BacktestRun(
                    experiment_id=None,
                    strategy_key=inst.strategy_key,
                    strategy_params=inst.params or {},
                    market_type=inst.market_type,
                    symbol=inst.symbol,
                    timeframe=inst.timeframe,
                    initial_equity=inst.initial_equity,
                    final_equity=inst.initial_equity,
                    total_return_pct=0.0,
                    annual_return_pct=0.0,
                    max_drawdown_pct=0.0,
                    sharpe=0.0,
                    calmar=0.0,
                    win_rate=0.0,
                    profit_factor=0.0,
                    trades_count=0,
                    fee_paid=0.0,
                    promotion_status="none",
                )
                session.add(run)
                session.flush()
                self._live_run_id = run.id
                session.commit()
                logger.info("Created live run %d for instance %d", run.id, self.instance_id)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=POLL_INTERVAL + 2)
            self._thread = None
        # Flush remaining candles on stop
        self._last_flush_ts = 0  # Force flush
        self._flush_candle_buffer()

    def _run_loop(self) -> None:
        logger.info("Runner started for instance %s (poll every %ds)", self.instance_id, POLL_INTERVAL)
        # Initial fetch to populate cache
        try:
            self._tick()
        except Exception:
            logger.exception("Initial tick failed for instance %s", self.instance_id)

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=POLL_INTERVAL)
            if self._stop_event.is_set():
                break
            try:
                self._tick()
            except Exception:
                logger.exception("Tick failed for instance %s", self.instance_id)
        logger.info("Runner stopped for instance %s", self.instance_id)

    def _tick(self) -> None:
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            if not inst:
                return
            if inst.status not in {"okx_demo_running", "okx_live_running"}:
                return
            symbol = inst.symbol
            timeframe = inst.timeframe
            market_type = inst.market_type
            broker_mode = inst.broker_mode
            strategy_key = inst.strategy_key
            params = inst.params or {}
            order_usdt = inst.order_usdt

        # 1. Fetch latest ticker and completed candles
        ticker_price, ticker_ts = self._fetch_ticker(symbol)
        completed_candles = self._fetch_and_cache(symbol, timeframe, market_type)

        if not completed_candles or len(completed_candles) < 5:
            logger.warning("Not enough candles for %s %s: %d", symbol, timeframe, len(completed_candles or []))
            return

        if ticker_price > 0:
            self._state["last_price"] = ticker_price

        # 2. Build a synthetic current candle using ticker price
        current_candle = CandleData(
            ts=ticker_ts or datetime.now(timezone.utc),
            open=completed_candles[-1].close,
            high=max(completed_candles[-1].close, ticker_price) if ticker_price > 0 else completed_candles[-1].high,
            low=min(completed_candles[-1].close, ticker_price) if ticker_price > 0 else completed_candles[-1].low,
            close=ticker_price if ticker_price > 0 else completed_candles[-1].close,
            volume=0,
            completed=False,
        )

        # 3. Strategy signal check (completed candles + current live candle)
        candles_for_signal = completed_candles + [current_candle]
        strategy = create_strategy(strategy_key, params)
        position_size = self._state.get("position_size", 0.0)
        context = StrategyContext(
            candles=candles_for_signal,
            position_size=position_size,
            order_usdt=order_usdt,
            state=self._state,
        )
        intents = strategy.intents(context)

        # 4. Deduplicate: only execute if signal is new (compare with last signal)
        if intents:
            signal_key = (intents[0].side, intents[0].reason)
            if self._last_signal_ts == completed_candles[-1].ts and self._last_signal_key == signal_key:
                intents = []  # Same signal on same candle, skip
            else:
                self._last_signal_ts = completed_candles[-1].ts
                self._last_signal_key = signal_key

        # 5. Execute immediately at ticker price
        exec_price = ticker_price if ticker_price > 0 else completed_candles[-1].close
        for intent in intents:
            fill, error = self._execute(intent, broker_mode, symbol, market_type, exec_price)
            if fill:
                self._apply_fill_to_state(fill)
                self._record_trade(fill, symbol, market_type, broker_mode, intent.reason)
            elif error:
                self._record_failed_trade(intent, symbol, market_type, broker_mode, exec_price, error)
                self._pause_instance_after_order_error(error, broker_mode)

        self._record_equity(exec_price)

    def _fetch_ticker(self, symbol: str) -> tuple[float, datetime]:
        """Fetch latest price from OKX."""
        try:
            gateway = OKXGateway(self.settings, "okx_demo", "spot")
            client = gateway.create_ccxt_client(authenticated=False)
            ticker = client.fetch_ticker(symbol)
            price = float(ticker.get("last", 0))
            ts = datetime.fromtimestamp(float(ticker.get("timestamp", 0)) / 1000, tz=timezone.utc) if ticker.get("timestamp") else datetime.now(timezone.utc)
            return price, ts
        except Exception:
            logger.warning("Failed to fetch ticker for %s", symbol, exc_info=True)
            return 0.0, datetime.now(timezone.utc)

    def _fetch_and_cache(self, symbol: str, timeframe: str, market_type: str) -> list[CandleData]:
        """Fetch latest candles from OKX, buffer for batch write to database."""
        try:
            gateway = OKXGateway(self.settings, "okx_demo", market_type)
            fresh = gateway.fetch_candles(symbol=symbol, timeframe=timeframe, limit=200)
        except Exception:
            logger.warning("Failed to fetch candles from OKX, using cache", exc_info=True)
            with self.database.session() as session:
                return self.market_data.list_candles(
                    session, market_type=market_type, symbol=symbol,
                    timeframe=timeframe, limit=200, completed_only=True, latest=True,
                )

        # Buffer candles for batch write
        if fresh:
            self._candle_buffer.append((market_type, symbol, timeframe, fresh))
            new_ts = fresh[-1].ts
            if new_ts != self._last_candle_ts:
                completed_count = sum(1 for c in fresh if c.completed)
                logger.info("Fetched %d candles (%d completed) for %s %s", len(fresh), completed_count, symbol, timeframe)
                self._last_candle_ts = new_ts

        # Flush buffer to database if interval elapsed
        self._flush_candle_buffer()

        return [c for c in fresh if c.completed]

    def _flush_candle_buffer(self) -> None:
        """Write buffered candles to database."""
        import time
        now = time.time()
        if now - self._last_flush_ts < CACHE_FLUSH_INTERVAL:
            return
        if not self._candle_buffer:
            return

        buffer = self._candle_buffer.copy()
        self._candle_buffer.clear()

        try:
            with self.database.session() as session:
                total = 0
                for market_type, symbol, timeframe, candles in buffer:
                    count = self.market_data.upsert_candles(
                        session,
                        market_type=market_type,
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=candles,
                        source="okx",
                    )
                    total += count
                session.commit()
            self._last_flush_ts = now
            logger.info("Flushed %d candles to database", total)
        except Exception:
            logger.warning("Failed to flush candles to database", exc_info=True)
            # Put buffer back for retry
            self._candle_buffer.extend(buffer)

    def _execute(
        self, intent, broker_mode: str, symbol: str, market_type: str, exec_price: float,
    ) -> tuple[Fill | None, str | None]:
        """Returns (fill, error_message). Error message is set if order failed."""
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            fee_rate = inst.fee_rate if inst else 0.001
            account_id = inst.account_id if inst else None
            allow_live = bool(inst.allow_live) if inst else False
            account = session.get(AccountConfig, account_id) if account_id else None

        if broker_mode in {"okx_demo", "okx_live"}:
            if account is None:
                return None, f"{broker_mode} 运行必须先绑定账户中心账户"
            if not account.is_active:
                return None, f"账户 {account.name} 未启用"
            if account.account_type != broker_mode:
                return None, f"{broker_mode} 运行不能使用 {account.account_type} 账户"
            account_settings = _settings_for_account(account, self.settings)
        else:
            return None, "运行中心只支持 OKX Demo 和 OKX Live"

        if exec_price <= 0:
            return None, "exec_price is zero"

        order_price = intent.limit_price if intent.order_type == "limit" and intent.limit_price else exec_price
        amount = intent.amount or (float(intent.quote_amount or 0.0) / order_price)
        if amount <= 0:
            return None, "calculated amount is zero"

        try:
            gateway = OKXGateway(account_settings, broker_mode, market_type)
            if intent.side == "sell":
                base_ccy = _symbol_base_ccy(symbol)
                balance_data = gateway.fetch_account_balance(base_ccy)
                if balance_data.get("code") != "0":
                    return None, balance_data.get("msg") or "OKX account balance unavailable"
                free_balance = _free_balance_from_okx(balance_data, base_ccy)
                if free_balance <= 0:
                    return None, f"{base_ccy} 可用余额不足"
                if amount > free_balance:
                    amount = free_balance * 0.999
                    if amount <= 0:
                        return None, f"{base_ccy} 可用余额不足"
            order = gateway.place_order(
                symbol=symbol, side=intent.side, amount=amount,
                order_type=intent.order_type,
                price=order_price if intent.order_type == "limit" else None,
                instance_allow_live=allow_live if broker_mode == "okx_live" else False,
                confirmation=account_settings.live_confirm_phrase if broker_mode == "okx_live" else None,
            )
            notional = amount * order_price
            fee = notional * fee_rate
            return Fill(
                side=intent.side, amount=amount, price=order_price, fee=fee,
                pnl=0.0, order_type=intent.order_type,
                meta={"execution": "okx", "order_id": _order_id(order)},
            ), None
        except Exception as e:
            error_msg = str(e)
            logger.warning("Order failed for %s: %s", symbol, error_msg)
            return None, error_msg

    def _apply_fill_to_state(self, fill: Fill) -> None:
        cash = float(self._state.get("cash", 0.0))
        position_size = float(self._state.get("position_size", 0.0))
        avg_entry_price = float(self._state.get("avg_entry_price", 0.0))
        notional = fill.amount * fill.price
        if fill.side == "buy":
            previous_cost = avg_entry_price * position_size
            position_size += fill.amount
            cash -= notional + fill.fee
            avg_entry_price = (previous_cost + notional) / position_size if position_size > 0 else 0.0
            fill.pnl = 0.0
        else:
            amount = min(fill.amount, position_size)
            fill.amount = amount
            realized = (fill.price - avg_entry_price) * amount - fill.fee
            cash += amount * fill.price - fill.fee
            position_size = max(0.0, position_size - amount)
            if position_size <= 1e-12:
                position_size = 0.0
                avg_entry_price = 0.0
            fill.pnl = realized
        self._state.update(
            {
                "cash": cash,
                "position_size": position_size,
                "avg_entry_price": avg_entry_price,
                "last_price": fill.price,
            }
        )

    def _record_trade(self, fill: Fill, symbol: str, market_type: str, broker_mode: str, reason: str) -> None:
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            account_id = inst.account_id if inst else None
            trade = Trade(
                run_id=self._live_run_id,
                instance_id=self.instance_id,
                account_id=account_id,
                ts=datetime.now(timezone.utc),
                broker_mode=broker_mode,
                market_type=market_type,
                symbol=symbol,
                side=fill.side,
                order_type=fill.order_type,
                amount=fill.amount,
                price=fill.price,
                fee=fill.fee,
                pnl=fill.pnl,
                external_order_id=fill.meta.get("order_id"),
                meta={"reason": reason, **fill.meta},
            )
            session.add(trade)
            session.commit()
        logger.info("TRADE: %s %s %.6f @ %.2f", fill.side, symbol, fill.amount, fill.price)

    def _record_failed_trade(self, intent, symbol: str, market_type: str, broker_mode: str, price: float, error: str) -> None:
        amount = intent.amount or ((intent.quote_amount or 0.0) / price if price > 0 else 0.0)
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            account_id = inst.account_id if inst else None
            trade = Trade(
                run_id=self._live_run_id,
                instance_id=self.instance_id,
                account_id=account_id,
                ts=datetime.now(timezone.utc),
                broker_mode=broker_mode,
                market_type=market_type,
                symbol=symbol,
                side=intent.side,
                order_type=intent.order_type,
                amount=0,
                price=price,
                fee=0,
                pnl=0,
                meta={"reason": intent.reason, "status": "failed", "error": error, "attempted_amount": amount},
            )
            session.add(trade)
            session.commit()
        logger.warning("FAILED TRADE: %s %s @ %.2f - %s", intent.side, symbol, price, error)

    def _pause_instance_after_order_error(self, error: str, broker_mode: str) -> None:
        with self.database.session() as session:
            inst = session.get(StrategyInstance, self.instance_id)
            if not inst:
                return
            inst.status = "paused"
            session.add(
                AuditEvent(
                    action="instance.auto_pause",
                    status="warning",
                    message=f"paused {inst.name} after order error",
                    meta={"id": inst.id, "broker_mode": broker_mode, "fatal": _is_fatal_order_error(error), "error": error},
                )
            )
            session.commit()
        self._stop_event.set()

    def _record_equity(self, price: float) -> None:
        if not self._live_run_id:
            return
        cash = self._state.get("cash", 10000)
        pos = self._state.get("position_size", 0.0)
        equity = cash + pos * price
        with self.database.session() as session:
            ep = EquityPoint(
                run_id=self._live_run_id,
                ts=datetime.now(timezone.utc),
                equity=equity,
                cash=cash,
                position_value=pos * price,
            )
            session.add(ep)
            session.commit()


class RunnerManager:
    """Manages all active strategy runners."""

    def __init__(self, settings: AppSettings, database: Database, market_data: MarketDataService):
        self.settings = settings
        self.database = database
        self.market_data = market_data
        self._runners: dict[int, StrategyRunner] = {}

    def start_instance(self, instance_id: int) -> None:
        if instance_id in self._runners and self._runners[instance_id].running:
            return
        runner = StrategyRunner(instance_id, self.settings, self.database, self.market_data)
        runner.start()
        self._runners[instance_id] = runner
        logger.info("Started runner for instance %s", instance_id)

    def stop_instance(self, instance_id: int) -> None:
        runner = self._runners.pop(instance_id, None)
        if runner:
            runner.stop()
            logger.info("Stopped runner for instance %s", instance_id)

    def stop_all(self) -> None:
        for instance_id in list(self._runners):
            self.stop_instance(instance_id)

    def is_running(self, instance_id: int) -> bool:
        runner = self._runners.get(instance_id)
        return runner is not None and runner.running

    def update_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        for runner in self._runners.values():
            runner.settings = settings

    def restore_running_instances(self) -> None:
        """Restore runners for instances that were running when the server stopped."""
        from sqlalchemy import select
        running_statuses = ["okx_demo_running", "okx_live_running"]
        with self.database.session() as session:
            stale_instances = session.scalars(
                select(StrategyInstance).where(
                    (StrategyInstance.enabled.is_(False)) | (StrategyInstance.status == "okx_live_running"),
                    StrategyInstance.status.in_(running_statuses),
                )
            ).all()
            for inst in stale_instances:
                inst.status = "paused"

            instances = session.scalars(
                select(StrategyInstance).where(
                    StrategyInstance.enabled.is_(True),
                    StrategyInstance.status == "okx_demo_running",
                )
            ).all()
            for inst in instances:
                self.start_instance(inst.id)
                logger.info("Restored runner for instance %s (%s)", inst.id, inst.name)
