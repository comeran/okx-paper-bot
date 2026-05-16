from __future__ import annotations

from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.risk import RiskConfig, size_order
from okx_paper_bot.store import TradeStore
from okx_paper_bot.strategy import moving_average_signal
from okx_paper_bot.exchange import fetch_close_prices


class TradingBot:
    def __init__(self, config: BotConfig, account: PaperAccount, store: TradeStore):
        self.config = config
        self.account = account
        self.store = store

    def on_prices(self, closes: list[float]) -> dict:
        signal = moving_average_signal(closes, fast=self.config.fast_window, slow=self.config.slow_window)
        if signal == "hold":
            return {"signal": "hold", "order": None}

        price = closes[-1]
        if signal == "buy":
            amount = size_order(
                self.account.balance_usdt,
                price,
                RiskConfig(
                    order_usdt=self.config.order_usdt,
                    max_position_fraction=self.config.max_position_fraction,
                ),
            )
        else:
            amount = self.account.positions.get(self.config.symbol, 0.0)

        order = self.account.execute_market_order(self.config.symbol, signal, amount, price)
        if order["status"] == "closed":
            self.store.record_trade(
                self.config.symbol,
                signal,
                amount=order["amount"],
                price=order["price"],
                order_id=order["id"],
            )
        return {"signal": signal, "order": order}

    def run_once_from_exchange(self, exchange) -> dict:
        try:
            closes = fetch_close_prices(
                exchange,
                symbol=self.config.symbol,
                timeframe=self.config.timeframe,
                limit=max(self.config.slow_window + 1, 2),
            )
        except Exception as exc:  # noqa: BLE001 - keep trading loop alive on exchange failures
            return {"signal": "error", "order": None, "error": str(exc)}
        return self.on_prices(closes)
