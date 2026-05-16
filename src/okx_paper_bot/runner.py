"""持续运行模块。"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore
from okx_paper_bot.stats import EquityTracker, PortfolioStats
from okx_paper_bot.notify import notify, format_status

BJT = timezone(timedelta(hours=8))

_TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "1w": 604800,
}


def _sleep_seconds(timeframe: str, interval_override: int = 0) -> int:
    if interval_override > 0:
        return interval_override
    return _TIMEFRAME_SECONDS.get(timeframe, 60)


class GracefulExit(SystemExit):
    pass


def _handle_signal(signum, frame):
    raise GracefulExit(0)


def run_loop(config: BotConfig | None = None) -> None:
    """持续运行交易机器人。"""
    if config is None:
        config = BotConfig.from_env()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    exchange = create_okx_exchange(config)
    account = PaperAccount(balance_usdt=config.initial_balance_usdt)
    store = TradeStore(config.db_path)
    bot = TradingBot(config, account, store)

    equity_file = Path(config.db_path).parent / "equity_history.json"
    tracker = EquityTracker(equity_file)

    interval = _sleep_seconds(config.timeframe, config.loop_interval_seconds)
    limit = max(config.slow_window + 1, 22)

    start_msg = (
        f"🚀 交易机器人启动\n"
        f"交易对: {config.symbol}\n"
        f"时间框架: {config.timeframe}\n"
        f"检查间隔: {interval}s\n"
        f"止损: {config.stop_loss_pct*100:.1f}% | 止盈: {config.take_profit_pct*100:.1f}%\n"
        f"移动止损: {config.trailing_stop_pct*100:.1f}%\n"
        f"初始余额: {config.initial_balance_usdt:.2f} USDT\n"
        f"Demo: {config.okx_demo}"
    )
    notify(start_msg, bot.notify_file)

    cycle = 0
    last_price = 0.0
    try:
        while True:
            cycle += 1
            now = datetime.now(BJT).strftime("%H:%M:%S")
            try:
                closes = fetch_close_prices(exchange, symbol=config.symbol, timeframe=config.timeframe, limit=limit)
                last_price = closes[-1]
                result = bot.on_prices(closes)
                sig = result["signal"]

                stats = PortfolioStats(
                    initial_balance=config.initial_balance_usdt,
                    current_balance=account.balance_usdt,
                    positions=dict(account.positions),
                    current_prices={config.symbol: last_price},
                )
                tracker.record(stats.snapshot())

                if sig == "hold" and cycle % 10 == 0:
                    status_msg = format_status(config.symbol, last_price, account.balance_usdt, account.positions, sig)
                    print(f"[{now}] {status_msg}")

            except GracefulExit:
                raise
            except Exception as exc:
                print(f"[{now}] ⚠️ 周期 {cycle} 错误: {exc}")

            time.sleep(interval)

    except GracefulExit:
        pass
    finally:
        total = account.balance_usdt
        for sym, qty in account.positions.items():
            total += qty * (last_price if last_price > 0 else 0)
        exit_msg = (
            f"🛑 交易机器人停止\n"
            f"运行周期: {cycle}\n"
            f"余额: {account.balance_usdt:.2f} USDT\n"
            f"持仓: {dict(account.positions)}\n"
            f"账户总值: {total:.2f} USDT"
        )
        notify(exit_msg, bot.notify_file)
