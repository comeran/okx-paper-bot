"""CLI 入口 - run / once / backtest / stats / dashboard。"""
from __future__ import annotations

import argparse
import sys

from okx_paper_bot.config import BotConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="OKX Paper Trading Bot")
    sub = parser.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="持续运行交易机器人")
    run_p.add_argument("--symbol", type=str)
    run_p.add_argument("--symbols", type=str, help="多交易对 (逗号分隔)")
    run_p.add_argument("--timeframe", type=str)
    run_p.add_argument("--strategy", choices=["ma_crossover", "rsi", "bollinger"])
    run_p.add_argument("--stop-loss", type=float)
    run_p.add_argument("--take-profit", type=float)
    run_p.add_argument("--trailing-stop", type=float)
    run_p.add_argument("--fee", type=float)
    run_p.add_argument("--slippage", type=float)
    run_p.add_argument("--tp1", type=float, help="第一档止盈 (0.05=5%%)")
    run_p.add_argument("--tp1-frac", type=float, help="第一档平仓比例 (0.5=一半)")
    run_p.add_argument("--tp2", type=float, help="第二档止盈")
    run_p.add_argument("--tp2-frac", type=float, help="第二档平仓比例")
    run_p.add_argument("--interval", type=int)
    run_p.add_argument("--live", action="store_true", help="实盘模式 (需要确认)")

    # backtest
    bt_p = sub.add_parser("backtest", help="回测策略")
    bt_p.add_argument("--symbol", default="BTC/USDT")
    bt_p.add_argument("--timeframe", default="1h")
    bt_p.add_argument("--days", type=int, default=30)
    bt_p.add_argument("--fast", type=int, default=5)
    bt_p.add_argument("--slow", type=int, default=20)
    bt_p.add_argument("--balance", type=float, default=10000)
    bt_p.add_argument("--order-usdt", type=float, default=500)
    bt_p.add_argument("--stop-loss", type=float, default=0.05)
    bt_p.add_argument("--take-profit", type=float, default=0.10)
    bt_p.add_argument("--trailing-stop", type=float, default=0.0)
    bt_p.add_argument("--detail", action="store_true")

    # stats
    stats_p = sub.add_parser("stats", help="查看收益统计")
    stats_p.add_argument("--symbol", default="BTC/USDT")

    # dashboard
    dash_p = sub.add_parser("dashboard", help="启动 Web Dashboard")
    dash_p.add_argument("--port", type=int, default=8080)
    dash_p.add_argument("--host", default="0.0.0.0")

    # once
    sub.add_parser("once", help="执行一次交易检查")

    args = parser.parse_args()

    if args.command == "run":
        _run(args)
    elif args.command == "backtest":
        _backtest(args)
    elif args.command == "stats":
        _stats(args)
    elif args.command == "dashboard":
        _dashboard(args)
    else:
        _once()


def _apply_overrides(config: BotConfig, args) -> BotConfig:
    overrides = {}
    mapping = {
        "symbol": "symbol", "symbols": "symbols", "timeframe": "timeframe",
        "strategy": "strategy_name", "stop_loss": "stop_loss_pct",
        "take_profit": "take_profit_pct", "trailing_stop": "trailing_stop_pct",
        "fee": "fee_pct", "slippage": "slippage_pct",
        "tp1": "tp1_pct", "tp1_frac": "tp1_fraction",
        "tp2": "tp2_pct", "tp2_frac": "tp2_fraction",
        "interval": "loop_interval_seconds",
    }
    for arg_key, cfg_key in mapping.items():
        val = getattr(args, arg_key, None)
        if val is not None:
            if arg_key == "symbols" and isinstance(val, str):
                val = tuple(s.strip() for s in val.split(","))
            overrides[cfg_key] = val
    if overrides:
        return config.__class__(**{**config.__dict__, **overrides})
    return config


def _run(args) -> None:
    from okx_paper_bot.runner import run_loop
    config = _apply_overrides(BotConfig.from_env(), args)

    if args.live:
        # 实盘模式安全确认
        print("⚠️  警告: 你正在切换到实盘模式！")
        print("   这将使用真实资金进行交易。")
        print(f"   交易对: {', '.join(config.all_symbols)}")
        print(f"   初始余额: {config.initial_balance_usdt} USDT")
        print()
        confirm = input("输入 YES 确认实盘模式: ")
        if confirm.strip() != "YES":
            print("❌ 已取消")
            return
        config = config.__class__(**{**config.__dict__, "okx_demo": False})
        print("✅ 实盘模式已启用")
        print()

    run_loop(config)


def _once() -> None:
    from okx_paper_bot.bot import TradingBot
    from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
    from okx_paper_bot.paper import PaperAccount
    from okx_paper_bot.store import TradeStore
    config = BotConfig.from_env()
    exchange = create_okx_exchange(config)
    account = PaperAccount(balance_usdt=config.initial_balance_usdt, fee_pct=config.fee_pct, slippage_pct=config.slippage_pct)
    store = TradeStore(config.db_path)
    bot = TradingBot(config, account, store)
    for sym in config.all_symbols:
        result = bot.run_once_from_exchange(exchange, symbol=sym)
        print(f"[{sym}] {result}")
    print({"balance_usdt": account.balance_usdt, "positions": account.positions})


def _backtest(args) -> None:
    import time
    from okx_paper_bot.backtester import fetch_historical_candles, run_backtest
    from okx_paper_bot.exchange import create_okx_exchange
    config = BotConfig(symbol=args.symbol, timeframe=args.timeframe,
                       fast_window=args.fast, slow_window=args.slow,
                       initial_balance_usdt=args.balance, order_usdt=args.order_usdt,
                       stop_loss_pct=args.stop_loss, take_profit_pct=args.take_profit,
                       trailing_stop_pct=args.trailing_stop)
    exchange = create_okx_exchange(config)
    since_ms = int((time.time() - args.days * 86400) * 1000)
    print(f"📥 拉取 {args.symbol} 历史 K 线 ({args.timeframe}, {args.days} 天)...")
    candles = fetch_historical_candles(exchange, args.symbol, args.timeframe, since_ms)
    print(f"   获取到 {len(candles)} 根 K 线")
    if len(candles) < config.slow_window + 1:
        print(f"❌ K 线不足 ({len(candles)} < {config.slow_window + 1})")
        sys.exit(1)
    result = run_backtest(candles, config)
    print()
    print(result.summary())
    if args.detail and result.trades:
        print("\n📋 交易明细:")
        for i, t in enumerate(result.trades, 1):
            reason = {"signal": "MA交叉", "stop_loss": "止损", "take_profit": "止盈",
                      "trailing_stop": "移动止损", "end_of_data": "数据结束"}.get(t.exit_reason, t.exit_reason)
            print(f"  {i:2d}. {t.entry_time} | {t.entry_price:.2f} → {t.exit_price:.2f} | {t.pnl:+.2f} ({reason})")


def _stats(args) -> None:
    from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
    from okx_paper_bot.store import TradeStore
    from okx_paper_bot.stats import PortfolioStats, EquityTracker
    config = BotConfig.from_env()
    exchange = create_okx_exchange(config)
    store = TradeStore(config.db_path)
    trades = store.list_trades()
    closes = fetch_close_prices(exchange, args.symbol, config.timeframe, limit=2)
    price = closes[-1] if closes else 0
    balance = config.initial_balance_usdt
    positions: dict[str, float] = {}
    for t in trades:
        if t["side"] == "buy":
            balance -= t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) + t["amount"]
        elif t["side"].startswith("sell") or "tp" in t["side"]:
            balance += t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) - t["amount"]
            if positions.get(t["symbol"], 0) <= 1e-12:
                positions.pop(t["symbol"], None)
    stats = PortfolioStats(initial_balance=config.initial_balance_usdt, current_balance=balance,
                           positions=positions, current_prices={args.symbol: price}, trades=trades)
    print(stats.format_report())
    equity_file = config.db_path.parent / "equity_history.json"
    if equity_file.exists():
        tracker = EquityTracker(equity_file)
        if len(tracker.history) > 1:
            print(f"\n📈 权益历史: {len(tracker.history)} 条")
            print(f"   夏普比率: {tracker.sharpe_ratio():.2f}")
            print(f"   最大回撤: {tracker.max_drawdown()*100:.2f}%")


def _dashboard(args) -> None:
    from okx_paper_bot.dashboard import run_dashboard
    run_dashboard(port=args.port)


if __name__ == "__main__":
    main()
