from __future__ import annotations

import argparse

from okx_paper_bot.config import BotConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="OKX Paper Trading Bot")
    parser.add_argument("--run", action="store_true", help="持续运行模式")
    parser.add_argument("--symbol", type=str, help="交易对")
    parser.add_argument("--symbols", type=str, help="多交易对 (逗号分隔)")
    parser.add_argument("--timeframe", type=str, help="K线周期")
    parser.add_argument("--strategy", type=str, choices=["ma_crossover", "rsi", "bollinger"], help="策略")
    parser.add_argument("--stop-loss", type=float, help="止损百分比")
    parser.add_argument("--take-profit", type=float, help="止盈百分比")
    parser.add_argument("--trailing-stop", type=float, help="移动止损百分比")
    parser.add_argument("--fee", type=float, help="手续费百分比")
    parser.add_argument("--slippage", type=float, help="滑点百分比")
    parser.add_argument("--interval", type=int, help="循环间隔秒数")
    args = parser.parse_args()

    config = BotConfig.from_env()
    overrides = {}
    if args.symbol: overrides["symbol"] = args.symbol
    if args.symbols: overrides["symbols"] = tuple(s.strip() for s in args.symbols.split(","))
    if args.timeframe: overrides["timeframe"] = args.timeframe
    if args.strategy: overrides["strategy_name"] = args.strategy
    if args.stop_loss is not None: overrides["stop_loss_pct"] = args.stop_loss
    if args.take_profit is not None: overrides["take_profit_pct"] = args.take_profit
    if args.trailing_stop is not None: overrides["trailing_stop_pct"] = args.trailing_stop
    if args.fee is not None: overrides["fee_pct"] = args.fee
    if args.slippage is not None: overrides["slippage_pct"] = args.slippage
    if args.interval is not None: overrides["loop_interval_seconds"] = args.interval
    if overrides:
        config = config.__class__(**{**config.__dict__, **overrides})

    if args.run:
        from okx_paper_bot.runner import run_loop
        run_loop(config)
    else:
        from okx_paper_bot.bot import TradingBot
        from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
        from okx_paper_bot.paper import PaperAccount
        from okx_paper_bot.store import TradeStore

        exchange = create_okx_exchange(config)
        account = PaperAccount(balance_usdt=config.initial_balance_usdt,
                               fee_pct=config.fee_pct, slippage_pct=config.slippage_pct)
        store = TradeStore(config.db_path)
        bot = TradingBot(config, account, store)

        for sym in config.all_symbols:
            closes = fetch_close_prices(exchange, symbol=sym, timeframe=config.timeframe,
                                        limit=max(config.slow_window + 1, 22))
            result = bot.on_prices(closes, symbol=sym)
            print(f"[{sym}] {result}")
        print({"balance_usdt": account.balance_usdt, "positions": account.positions})


if __name__ == "__main__":
    main()
