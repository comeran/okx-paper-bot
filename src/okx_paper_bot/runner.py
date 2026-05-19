"""持续运行模块。"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig, StrategyInstance, load_strategy_instances
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


def _build_bot_config(config: BotConfig, inst: StrategyInstance) -> BotConfig:
    """Create a BotConfig override from a StrategyInstance."""
    return BotConfig(
        symbol=inst.symbols[0] if inst.symbols else config.symbol,
        symbols=tuple(inst.symbols),
        timeframe=inst.timeframe,
        okx_demo=config.okx_demo,
        strategy_name=inst.strategy,
        fast_window=inst.fast_window,
        slow_window=inst.slow_window,
        rsi_period=inst.rsi_period,
        rsi_buy=inst.rsi_buy,
        rsi_sell=inst.rsi_sell,
        bollinger_period=inst.bollinger_period,
        bollinger_std=inst.bollinger_std,
        initial_balance_usdt=config.initial_balance_usdt,
        order_usdt=inst.order_usdt,
        max_position_fraction=config.max_position_fraction,
        fee_pct=config.fee_pct,
        slippage_pct=config.slippage_pct,
        db_path=config.db_path,
        api_key=config.api_key,
        secret=config.secret,
        password=config.password,
        stop_loss_pct=inst.stop_loss_pct,
        take_profit_pct=inst.take_profit_pct,
        trailing_stop_pct=inst.trailing_stop_pct,
        tp1_pct=inst.tp1_pct,
        tp1_fraction=inst.tp1_fraction,
        tp2_pct=inst.tp2_pct,
        tp2_fraction=inst.tp2_fraction,
        notify_file=config.notify_file,
        loop_interval_seconds=config.loop_interval_seconds,
    )


def _sleep_for_instance(inst: StrategyInstance, default_interval: int) -> int:
    """Compute sleep seconds for a strategy instance."""
    if default_interval > 0:
        return default_interval
    return _TIMEFRAME_SECONDS.get(inst.timeframe, 60)


def run_loop(config: BotConfig | None = None) -> None:
    """持续运行交易机器人（支持多策略实例）。"""
    if config is None:
        config = BotConfig.from_env()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    exchange = create_okx_exchange(config)
    store = TradeStore(config.db_path)
    data_dir = Path(config.db_path).parent

    equity_file = data_dir / "equity_history.json"
    tracker = EquityTracker(equity_file)

    # Load strategy instances or fall back to legacy single strategy
    instances = load_strategy_instances()
    if not instances:
        instances = [StrategyInstance(
            name="default",
            strategy=config.strategy_name,
            symbols=config.all_symbols,
            timeframe=config.timeframe,
            fast_window=config.fast_window,
            slow_window=config.slow_window,
            rsi_period=config.rsi_period,
            rsi_buy=config.rsi_buy,
            rsi_sell=config.rsi_sell,
            bollinger_period=config.bollinger_period,
            bollinger_std=config.bollinger_std,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            trailing_stop_pct=config.trailing_stop_pct,
            tp1_pct=config.tp1_pct,
            tp1_fraction=config.tp1_fraction,
            tp2_pct=config.tp2_pct,
            tp2_fraction=config.tp2_fraction,
            order_usdt=config.order_usdt,
            equity=config.initial_balance_usdt,
        )]

    # Create independent PaperAccount per instance
    accounts: dict[str, PaperAccount] = {}
    bots: list[tuple[StrategyInstance, TradingBot]] = []
    for inst in instances:
        # Each instance has its own account file and equity
        acct_file = data_dir / f"account_{inst.name}.json"
        inst_equity = inst.equity if inst.equity > 0 else config.initial_balance_usdt
        acct = PaperAccount.load(acct_file, fallback_balance=inst_equity)
        accounts[inst.name] = acct
        inst_config = _build_bot_config(config, inst)
        bot = TradingBot(inst_config, acct, store, instance_name=inst.name)
        bots.append((inst, bot))
        pos_info = acct.positions if acct.positions else "空仓"
        print(f"📦 [{inst.name}] 余额: {acct.balance_usdt:.2f} | 持仓: {pos_info} | 分配权益: {inst_equity:.2f}")

    # Collect all unique symbols and determine min sleep interval
    all_symbols: list[str] = []
    seen_syms: set[str] = set()
    for inst, _ in bots:
        for s in inst.symbols:
            if s not in seen_syms:
                all_symbols.append(s)
                seen_syms.add(s)

    min_interval = min(_sleep_for_instance(inst, config.loop_interval_seconds) for inst, _ in bots)

    # Build strategy summary
    strat_lines = []
    for inst, _ in bots:
        strat_lines.append(f"  [{inst.name}] {inst.strategy} -> {', '.join(inst.symbols)} ({inst.timeframe})")

    start_msg = (
        f"🚀 交易机器人启动\n"
        f"策略实例: {len(bots)} 个\n"
        + "\n".join(strat_lines) + "\n"
        f"检查间隔: {min_interval}s\n"
        f"初始余额: {config.initial_balance_usdt:.2f} USDT\n"
        f"Demo: {config.okx_demo}"
    )
    notify(start_msg, bots[0][1].notify_file)

    cycle = 0
    last_prices: dict[str, float] = {}
    try:
        while True:
            cycle += 1
            now = datetime.now(BJT).strftime("%H:%M:%S")
            try:
                for inst, bot in bots:
                    # Per-instance limit based on slow window
                    limit = max(inst.slow_window + 1, 22)
                    for sym in inst.symbols:
                        closes = fetch_close_prices(exchange, symbol=sym, timeframe=inst.timeframe, limit=limit)
                        last_prices[sym] = closes[-1]
                        result = bot.on_prices(closes, symbol=sym)
                        sig = result["signal"]

                        if sig == "hold" and cycle % 10 == 0:
                            acct = accounts[inst.name]
                            status_msg = format_status(
                                f"[{inst.name}]{sym}", closes[-1],
                                acct.balance_usdt, acct.positions, sig,
                            )
                            print(f"[{now}] {status_msg}")

                # 记录权益快照（汇总所有账户）
                total_balance = sum(a.balance_usdt for a in accounts.values())
                total_positions = {}
                for a in accounts.values():
                    for sym, qty in a.positions.items():
                        total_positions[sym] = total_positions.get(sym, 0) + qty
                stats = PortfolioStats(
                    initial_balance=config.initial_balance_usdt,
                    current_balance=total_balance,
                    positions=total_positions,
                    current_prices=last_prices,
                )
                tracker.record(stats.snapshot())
                # 保存每个账户
                for name, acct in accounts.items():
                    acct.save(data_dir / f"account_{name}.json")

            except GracefulExit:
                for name, acct in accounts.items():
                    acct.save(data_dir / f"account_{name}.json")
                raise
            except Exception as exc:
                print(f"[{now}] ⚠️ 周期 {cycle} 错误: {exc}")

            time.sleep(min_interval)

    except GracefulExit:
        pass
    finally:
        total = sum(a.balance_usdt for a in accounts.values())
        for a in accounts.values():
            for sym, qty in a.positions.items():
                price = last_prices.get(sym, 0)
                total += qty * price
        exit_lines = [f"🛑 交易机器人停止", f"运行周期: {cycle}"]
        for inst, _ in bots:
            acct = accounts[inst.name]
            exit_lines.append(f"[{inst.name}] 余额: {acct.balance_usdt:.2f} | 持仓: {dict(acct.positions)}")
        exit_lines.append(f"账户总值: {total:.2f} USDT")
        exit_msg = "\n".join(exit_lines)
        notify(exit_msg, bots[0][1].notify_file)
