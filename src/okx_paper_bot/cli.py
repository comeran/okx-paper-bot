from __future__ import annotations

from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.exchange import create_okx_exchange, fetch_close_prices
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore


def main() -> None:
    config = BotConfig.from_env()
    exchange = create_okx_exchange(config)
    account = PaperAccount(balance_usdt=config.initial_balance_usdt)
    store = TradeStore(config.db_path)
    bot = TradingBot(config, account, store)

    closes = fetch_close_prices(
        exchange,
        symbol=config.symbol,
        timeframe=config.timeframe,
        limit=max(config.slow_window + 1, 2),
    )
    result = bot.on_prices(closes)
    print(result)
    print({"balance_usdt": account.balance_usdt, "positions": account.positions})


if __name__ == "__main__":
    main()
