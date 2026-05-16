from __future__ import annotations

import argparse
import sys

from okx_paper_bot.config import BotConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="OKX Paper Trading Bot")
    sub = parser.add_subparsers(dest="command")

    # run 子命令
    run_p = sub.add_parser("run", help="持续运行交易机器人")
    run_p.add_argument("--symbol", type=str, help="交易对")
    run_p.add_argument("--timeframe", type=str, help="K线周期")
    run_p.add_argument("--stop-loss", type=float, help="止损百分比")
    run_p.add_argument("--take-profit", type=float, help="止盈百分比")
    run_p.add_argument("--trailing-stop", type=float, help="移动止损百分比")
    run_p.add_argument("--interval", type=int, help="循环间隔秒数")

    # backtest 子命令
    bt_p = sub.add_parser("backtest", help="回测策略")
    bt_p.add_argument("--symbol", type=str, default="BTC/USDT", help="交易对")
    bt_p.add_argument("--timeframe", type=str, default="1h", help="K线周期")
    bt_p.add_argument("--days", type=int, default=30, help="回测天数")
    bt_p.add_argument("--fast", type=int, default=5, help="快速均线窗口")
    bt_p.add_argument("--slow", type=int, default=20, help="慢速均线窗口")
    bt_p.add_argument("--balance", type=float, default=10000, help="初始资金")
    bt_p.add_argument("--order-usdt", type=float, default=500, help="单笔下单金额")
    bt_p.add_argument("--stop-loss", type=float, default=0.05, help="止损百分比")
    bt_p.add_argument("--take-profit", type=float, default=0.10, help="止盈百分比")
    bt_p.add_argument("--trailing-stop", type=float, default=0.0, help="移动止损百分比")
    bt_p.add_argument("--detail", action="store_true", help="显示每笔交易明细")

    # stats 子命令
    stats_p = sub.add_parser("stats", help="查看收益统计")
    stats_p.add_argument("--symbol", type=str, default="BTC/USDT", help="交易对")

    # once 子命令（默认）
    sub.add_parser("once", help="执行一次交易检查")

    args = parser.parse_args()

    if args.command == "run":
        _run(args)
    elif args.command == "backtest":
        _backtest(args)
    elif args.command == "stats":
        _stats(args)
    else:
        _once()


def _apply_overrides(config: BotConfig, args) -> BotConfig:
    overrides = {}
    for attr, key in [("symbol", "symbol"), ("timeframe", "timeframe"),
                       ("stop_loss", "stop_loss_pct"), ("take_profit", "take_profit_pct"),
                       ("trailing_stop", "trailing_stop_pct"), ("interval", "loop_interval_seconds")]:
        val = getattr(args, attr, None)
        if val is not None:
            overrides[key] = val
    if overrides:
        return config.__class__(**{**config.__dict__, **overrides})
    return config


def _run(args) -> None:
    from okx_paper_bot.runner import run_loop
    config = BotConfig.from_env()
    config = _apply_overrides(config, args)
    run_loop(config)


def _once() -> None:
    from okx_paper_bot.bot import TradingBot
    from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
    from okx_paper_bot.paper import PaperAccount
    from okx_paper_bot.store import TradeStore

    config = BotConfig.from_env()
    exchange = create_okx_exchange(config)
    account = PaperAccount(balance_usdt=config.initial_balance_usdt)
    store = TradeStore(config.db_path)
    bot = TradingBot(config, account, store)
    result = bot.run_once_from_exchange(exchange)
    print(result)
    print({"balance_usdt": account.balance_usdt, "positions": account.positions})


def _backtest(args) -> None:
    import time
    from okx_paper_bot.backtester import fetch_historical_candles, run_backtest
    from okx_paper_bot.exchange import create_okx_exchange

    config = BotConfig(
        symbol=args.symbol, timeframe=args.timeframe,
        fast_window=args.fast, slow_window=args.slow,
        initial_balance_usdt=args.balance, order_usdt=args.order_usdt,
        stop_loss_pct=args.stop_loss, take_profit_pct=args.take_profit,
        trailing_stop_pct=args.trailing_stop,
    )
    exchange = create_okx_exchange(config)
    since_ms = int((time.time() - args.days * 86400) * 1000)

    print(f"📥 拉取 {args.symbol} 历史 K 线 ({args.timeframe}, {args.days} 天)...")
    candles = fetch_historical_candles(exchange, args.symbol, args.timeframe, since_ms)
    print(f"   获取到 {len(candles)} 根 K 线")

    if len(candles) < config.slow_window + 1:
        print(f"❌ K 线数量不足，需要至少 {config.slow_window + 1}")
        sys.exit(1)

    result = run_backtest(candles, config)
    print()
    print(result.summary())

    if args.detail and result.trades:
        print()
        print("📋 交易明细:")
        for i, t in enumerate(result.trades, 1):
            reason = {"signal": "MA交叉", "stop_loss": "止损", "take_profit": "止盈",
                      "trailing_stop": "移动止损", "end_of_data": "数据结束"}.get(t.exit_reason, t.exit_reason)
            print(f"  {i:2d}. {t.entry_time} | {t.entry_price:.2f} → {t.exit_price:.2f} | {t.pnl:+.2f} USDT ({reason})")


def _stats(args) -> None:
    from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
    from okx_paper_bot.paper import PaperAccount
    from okx_paper_bot.store import TradeStore
    from okx_paper_bot.stats import PortfolioStats, EquityTracker
    from pathlib import Path

    config = BotConfig.from_env()
    exchange = create_okx_exchange(config)
    store = TradeStore(config.db_path)
    trades = store.list_trades()

    # 获取当前价格
    closes = fetch_close_prices(exchange, args.symbol, config.timeframe, limit=2)
    price = closes[-1] if closes else 0

    # 从交易记录重建持仓（简化版）
    balance = config.initial_balance_usdt
    positions: dict[str, float] = {}
    for t in trades:
        if t["side"] == "buy":
            cost = t["amount"] * t["price"]
            balance -= cost
            positions[t["symbol"]] = positions.get(t["symbol"], 0) + t["amount"]
        elif t["side"] == "sell":
            revenue = t["amount"] * t["price"]
            balance += revenue
            positions[t["symbol"]] = positions.get(t["symbol"], 0) - t["amount"]
            if positions[t["symbol"]] <= 0:
                positions.pop(t["symbol"], None)

    stats = PortfolioStats(
        initial_balance=config.initial_balance_usdt,
        current_balance=balance,
        positions=positions,
        current_prices={args.symbol: price},
        trades=trades,
    )
    print(stats.format_report())

    # 权益历史
    equity_file = Path(config.db_path).parent / "equity_history.json"
    if equity_file.exists():
        tracker = EquityTracker(equity_file)
        if len(tracker.history) > 1:
            print()
            print(f"📈 权益历史: {len(tracker.history)} 条记录")
            print(f"   夏普比率: {tracker.sharpe_ratio():.2f}")
            print(f"   最大回撤: {tracker.max_drawdown()*100:.2f}%")


if __name__ == "__main__":
    main()
