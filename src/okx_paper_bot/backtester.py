from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from okx_paper_bot.backtest import BacktestResult, BacktestTrade
from okx_paper_bot.config import BotConfig
from okx_paper_bot.exchange import retry_call
from okx_paper_bot.risk import RiskConfig, StopLossConfig, check_stop_loss, size_order
from okx_paper_bot.strategy import moving_average_signal
from okx_paper_bot.strategies import get_strategy, STRATEGIES

BJT = timezone(timedelta(hours=8))


def fetch_historical_candles(
    exchange: Any,
    symbol: str,
    timeframe: str,
    since_ms: int,
    limit_per_call: int = 300,
    max_calls: int = 100,
) -> list[list]:
    """从交易所拉取历史 K 线数据，自动分页。

    返回: [[timestamp, open, high, low, close, volume], ...]
    """
    all_candles: list[list] = []
    since = since_ms

    for _ in range(max_calls):
        candles = retry_call(
            lambda s=since: exchange.fetch_ohlcv(symbol, timeframe, since=s, limit=limit_per_call),
            attempts=3,
            delay_seconds=1.0,
        )
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts == since:
            break
        since = last_ts + 1
        if len(candles) < limit_per_call:
            break

    # 去重并按时间排序
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    unique.sort(key=lambda x: x[0])
    return unique


def _get_signal_for_strategy(
    closes: list[float],
    strategy_name: str,
    config: BotConfig,
) -> str:
    """根据策略名称调用对应的信号函数。支持所有策略类型。"""
    if strategy_name == "ma_crossover":
        return moving_average_signal(closes, fast=config.fast_window, slow=config.slow_window)
    else:
        # Use strategy registry for rsi, bollinger, macd, etc.
        try:
            params = {}
            if strategy_name == "rsi":
                params = {"period": config.rsi_period, "oversold": config.rsi_buy, "overbought": config.rsi_sell}
            elif strategy_name == "bollinger":
                params = {"period": config.bollinger_period, "std_dev": config.bollinger_std}
            elif strategy_name == "macd":
                params = {"fast_period": config.fast_window, "slow_period": config.slow_window, "signal_period": 9}
            strat = get_strategy(strategy_name, **params)
            return strat.signal(closes)
        except (ValueError, KeyError):
            # Fallback to MA crossover
            return moving_average_signal(closes, fast=config.fast_window, slow=config.slow_window)


def run_backtest(
    candles: list[list],
    config: BotConfig,
    strategy_name: str | None = None,
) -> BacktestResult:
    """在历史 K 线数据上运行回测。

    Args:
        candles: [[timestamp_ms, open, high, low, close, volume], ...]
        config: 机器人配置（策略参数、止损止盈参数）
        strategy_name: 策略名称（覆盖 config.strategy_name）

    Returns:
        BacktestResult 回测结果
    """
    strat_name = strategy_name or config.strategy_name

    # Determine minimum data points needed
    if strat_name == "rsi":
        min_points = config.rsi_period + 2
    elif strat_name == "bollinger":
        min_points = config.bollinger_period + 1
    elif strat_name == "macd":
        min_points = config.slow_window + 10 + 1  # slow_period + signal_period + 1
    else:
        min_points = config.slow_window + 1

    if len(candles) < min_points:
        raise ValueError(f"需要至少 {min_points} 根 K 线，实际 {len(candles)}")

    balance = config.initial_balance_usdt
    symbol = config.symbol
    risk_config = RiskConfig(order_usdt=config.order_usdt, max_position_fraction=config.max_position_fraction)
    sl_config = StopLossConfig(
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        trailing_stop_pct=config.trailing_stop_pct,
    )

    trades: list[BacktestTrade] = []
    position_amount = 0.0
    entry_price = 0.0
    highest_price = 0.0
    current_trade: BacktestTrade | None = None

    closes: list[float] = []
    start_time = datetime.fromtimestamp(candles[0][0] / 1000, tz=BJT).strftime("%Y-%m-%d %H:%M")
    end_time = ""

    for candle in candles:
        ts_ms, _o, _h, _l, close, _v = candle
        price = float(close)
        closes.append(price)
        bar_time = datetime.fromtimestamp(ts_ms / 1000, tz=BJT).strftime("%Y-%m-%d %H:%M")
        end_time = bar_time

        if len(closes) < min_points:
            continue

        # 1. 止损止盈检查（持仓中）
        if position_amount > 0:
            if price > highest_price:
                highest_price = price

            trigger = check_stop_loss(entry_price, price, highest_price, sl_config)
            if trigger:
                pnl = (price - entry_price) * position_amount
                balance += position_amount * price
                if current_trade:
                    current_trade.exit_time = bar_time
                    current_trade.exit_price = price
                    current_trade.pnl = pnl
                    current_trade.pnl_pct = (price - entry_price) / entry_price
                    current_trade.exit_reason = trigger
                    trades.append(current_trade)
                position_amount = 0.0
                entry_price = 0.0
                highest_price = 0.0
                current_trade = None
                continue

        # 2. 策略信号（支持全部策略类型）
        signal = _get_signal_for_strategy(closes, strat_name, config)

        if signal == "buy" and position_amount == 0:
            amount = size_order(balance, price, risk_config)
            if amount > 0:
                cost = amount * price
                balance -= cost
                position_amount = amount
                entry_price = price
                highest_price = price
                current_trade = BacktestTrade(
                    entry_time=bar_time,
                    entry_price=price,
                    amount=amount,
                    side="buy",
                )

        elif signal == "sell" and position_amount > 0:
            pnl = (price - entry_price) * position_amount
            balance += position_amount * price
            if current_trade:
                current_trade.exit_time = bar_time
                current_trade.exit_price = price
                current_trade.pnl = pnl
                current_trade.pnl_pct = (price - entry_price) / entry_price
                current_trade.exit_reason = "signal"
                trades.append(current_trade)
            position_amount = 0.0
            entry_price = 0.0
            highest_price = 0.0
            current_trade = None

    # 如果还有持仓，按最后价格平仓
    if position_amount > 0 and closes:
        final_price = closes[-1]
        pnl = (final_price - entry_price) * position_amount
        balance += position_amount * final_price
        if current_trade:
            current_trade.exit_time = end_time
            current_trade.exit_price = final_price
            current_trade.pnl = pnl
            current_trade.pnl_pct = (final_price - entry_price) / entry_price
            current_trade.exit_reason = "end_of_data"
            trades.append(current_trade)

    return BacktestResult(
        symbol=symbol,
        timeframe=config.timeframe,
        start_time=start_time,
        end_time=end_time,
        initial_balance=config.initial_balance_usdt,
        final_balance=balance,
        trades=trades,
    )
