"""K-line event backtesting engine."""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from okx_paper_bot.brokers import Fill, PaperAccount
from okx_paper_bot.market import CandleData, timeframe_seconds
from okx_paper_bot.persistence.models import BacktestRun, EquityPoint, Trade
from okx_paper_bot.strategies import OrderIntent, StrategyContext, create_strategy


@dataclass(frozen=True)
class EquitySample:
    ts: datetime
    equity: float
    cash: float
    position_value: float


@dataclass(frozen=True)
class BacktestTrade:
    ts: datetime
    side: str
    order_type: str
    amount: float
    price: float
    fee: float
    pnl: float
    reason: str


@dataclass
class BacktestResult:
    strategy_key: str
    strategy_params: dict[str, Any]
    market_type: str
    symbol: str
    timeframe: str
    initial_equity: float
    final_equity: float
    metrics: dict[str, float | int]
    equity_curve: list[EquitySample] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    code_version: str = "unknown"


class EventBacktester:
    """Conservative candle-close signal, next-candle execution backtester."""

    def run(
        self,
        *,
        strategy_key: str,
        strategy_params: dict[str, Any] | None,
        candles: list[CandleData],
        market_type: str,
        symbol: str,
        timeframe: str,
        initial_equity: float = 10000.0,
        order_usdt: float = 500.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
    ) -> BacktestResult:
        completed = [c for c in candles if c.completed]
        if len(completed) < 3:
            raise ValueError("at least three completed candles are required")

        strategy = create_strategy(strategy_key, strategy_params or {})
        account = PaperAccount(initial_equity, fee_rate=fee_rate, slippage_rate=slippage_rate)
        state: dict[str, Any] = {}
        trades: list[BacktestTrade] = []
        equity_curve: list[EquitySample] = [
            EquitySample(completed[0].ts, initial_equity, initial_equity, 0.0)
        ]

        history: list[CandleData] = [completed[0]]
        for idx in range(1, len(completed) - 1):
            history.append(completed[idx])
            execution_candle = completed[idx + 1]
            context = StrategyContext(
                candles=history,
                position_size=account.position_size,
                order_usdt=order_usdt,
                state=state,
            )
            intents = strategy.intents(context)
            for intent in intents:
                fill = self._execute_intent(account, intent, execution_candle)
                if fill is None:
                    continue
                trades.append(
                    BacktestTrade(
                        ts=execution_candle.ts,
                        side=fill.side,
                        order_type=fill.order_type,
                        amount=fill.amount,
                        price=fill.price,
                        fee=fill.fee,
                        pnl=fill.pnl,
                        reason=intent.reason,
                    )
                )
            mark_price = execution_candle.close
            equity_curve.append(
                EquitySample(
                    execution_candle.ts,
                    account.equity(mark_price),
                    account.cash,
                    account.position_size * mark_price,
                )
            )

        final_equity = equity_curve[-1].equity
        metrics = calculate_metrics(equity_curve, trades, initial_equity, timeframe=timeframe)
        return BacktestResult(
            strategy_key=strategy_key,
            strategy_params=strategy_params or {},
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            initial_equity=initial_equity,
            final_equity=final_equity,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            start_ts=completed[0].ts,
            end_ts=completed[-1].ts,
            code_version=current_code_version(),
        )

    def _execute_intent(self, account: PaperAccount, intent: OrderIntent, candle: CandleData) -> Fill | None:
        if intent.side == "buy":
            quote = float(intent.quote_amount or 0.0)
            if intent.order_type == "limit":
                if intent.limit_price is None or candle.low > intent.limit_price:
                    return None
                return account.buy(price=intent.limit_price, quote_amount=quote, order_type="limit")
            return account.buy(price=candle.open, quote_amount=quote, order_type="market")
        if intent.side == "sell":
            amount = float(intent.amount or account.position_size)
            if intent.order_type == "limit":
                if intent.limit_price is None or candle.high < intent.limit_price:
                    return None
                return account.sell(price=intent.limit_price, amount=amount, order_type="limit")
            return account.sell(price=candle.open, amount=amount, order_type="market")
        return None


def calculate_metrics(
    equity_curve: list[EquitySample], trades: list[BacktestTrade], initial_equity: float,
    timeframe: str = "1d",
) -> dict[str, float | int]:
    final_equity = equity_curve[-1].equity if equity_curve else initial_equity
    total_return_pct = (final_equity / initial_equity - 1) * 100 if initial_equity > 0 else 0.0
    max_drawdown_pct = _max_drawdown_pct([p.equity for p in equity_curve])
    returns = [
        equity_curve[i].equity / equity_curve[i - 1].equity - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1].equity > 0
    ]
    annualization = math.sqrt(365 * 86400 / timeframe_seconds(timeframe))
    sharpe = _sharpe(returns, annualization)
    days = max((equity_curve[-1].ts - equity_curve[0].ts).total_seconds() / 86400, 1 / 24)
    annual_return_pct = ((final_equity / initial_equity) ** (365 / days) - 1) * 100 if initial_equity > 0 else 0.0
    calmar = annual_return_pct / abs(max_drawdown_pct) if max_drawdown_pct < 0 else 0.0
    closed = [t for t in trades if t.side == "sell"]
    wins = [t.pnl for t in closed if t.pnl > 0]
    losses = [t.pnl for t in closed if t.pnl < 0]
    win_rate = len(wins) / len(closed) if closed else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    fee_paid = sum(t.fee for t in trades)
    return {
        "total_return_pct": round(total_return_pct, 6),
        "annual_return_pct": round(annual_return_pct, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "sharpe": round(sharpe, 6),
        "calmar": round(calmar, 6),
        "win_rate": round(win_rate, 6),
        "profit_factor": round(profit_factor, 6),
        "trades_count": len(trades),
        "fee_paid": round(fee_paid, 8),
    }


def persist_backtest_result(session: Session, result: BacktestResult, experiment_id: int | None = None) -> BacktestRun:
    run = BacktestRun(
        experiment_id=experiment_id,
        strategy_key=result.strategy_key,
        strategy_params=result.strategy_params,
        market_type=result.market_type,
        symbol=result.symbol,
        timeframe=result.timeframe,
        start_ts=result.start_ts,
        end_ts=result.end_ts,
        initial_equity=result.initial_equity,
        final_equity=result.final_equity,
        total_return_pct=float(result.metrics["total_return_pct"]),
        annual_return_pct=float(result.metrics["annual_return_pct"]),
        max_drawdown_pct=float(result.metrics["max_drawdown_pct"]),
        sharpe=float(result.metrics["sharpe"]),
        calmar=float(result.metrics["calmar"]),
        win_rate=float(result.metrics["win_rate"]),
        profit_factor=float(result.metrics["profit_factor"]),
        trades_count=int(result.metrics["trades_count"]),
        fee_paid=float(result.metrics["fee_paid"]),
        code_version=result.code_version,
    )
    session.add(run)
    session.flush()
    for point in result.equity_curve:
        session.add(
            EquityPoint(
                run_id=run.id,
                ts=point.ts,
                equity=point.equity,
                cash=point.cash,
                position_value=point.position_value,
            )
        )
    for trade in result.trades:
        session.add(
            Trade(
                run_id=run.id,
                ts=trade.ts,
                broker_mode="backtest",
                market_type=result.market_type,
                symbol=result.symbol,
                side=trade.side,
                order_type=trade.order_type,
                amount=trade.amount,
                price=trade.price,
                fee=trade.fee,
                pnl=trade.pnl,
                meta={"reason": trade.reason},
            )
        )
    return run


def _max_drawdown_pct(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst * 100


def _sharpe(returns: list[float], annualization: float) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std <= 1e-12:
        return 0.0
    return mean / std * annualization


_CODE_VERSION: str | None = None


def current_code_version() -> str:
    global _CODE_VERSION
    if _CODE_VERSION is not None:
        return _CODE_VERSION
    try:
        _CODE_VERSION = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        _CODE_VERSION = "unknown"
    return _CODE_VERSION
