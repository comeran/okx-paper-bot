from __future__ import annotations

from pathlib import Path

from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.risk import RiskConfig, StopLossConfig, size_order, check_stop_loss
from okx_paper_bot.store import TradeStore
from okx_paper_bot.strategy import moving_average_signal
from okx_paper_bot.exchange import fetch_close_prices
from okx_paper_bot.notify import (
    notify,
    format_trade_signal,
    format_error,
    format_status,
)


class TradingBot:
    def __init__(
        self,
        config: BotConfig,
        account: PaperAccount,
        store: TradeStore,
        notify_file: Path | str | None = None,
    ):
        self.config = config
        self.account = account
        self.store = store
        self.notify_file = notify_file or config.notify_file
        self._queue_file = Path("data/notify_queue.jsonl")
        # 跟踪入场价和最高价（用于止损止盈）
        self._entry_prices: dict[str, float] = {}
        self._highest_prices: dict[str, float] = {}

    def on_prices(self, closes: list[float]) -> dict:
        price = closes[-1]
        symbol = self.config.symbol

        # 1. 先检查止损止盈（有持仓时）
        held = self.account.positions.get(symbol, 0.0)
        if held > 0 and symbol in self._entry_prices:
            # 更新最高价
            if price > self._highest_prices.get(symbol, 0):
                self._highest_prices[symbol] = price

            sl_config = StopLossConfig(
                stop_loss_pct=self.config.stop_loss_pct,
                take_profit_pct=self.config.take_profit_pct,
                trailing_stop_pct=self.config.trailing_stop_pct,
            )
            trigger = check_stop_loss(
                entry_price=self._entry_prices[symbol],
                current_price=price,
                highest_price=self._highest_prices.get(symbol, price),
                config=sl_config,
            )
            if trigger:
                order = self.account.execute_market_order(symbol, "sell", held, price)
                if order["status"] == "closed":
                    self.store.record_trade(symbol, "sell", amount=order["amount"], price=order["price"], order_id=order["id"])
                    pnl = (price - self._entry_prices[symbol]) * held
                    reason = f"{trigger} 触发, 盈亏: {pnl:+.2f} USDT"
                    msg = format_trade_signal(symbol, trigger, price, order["amount"], "closed", self.account.balance_usdt, self.account.positions, reason=reason)
                    notify(msg, self.notify_file, self._queue_file)
                    # 清理跟踪
                    self._entry_prices.pop(symbol, None)
                    self._highest_prices.pop(symbol, None)
                    return {"signal": trigger, "order": order, "reason": reason}
                return {"signal": trigger, "order": order}

        # 2. MA 交叉信号
        signal = moving_average_signal(closes, fast=self.config.fast_window, slow=self.config.slow_window)
        if signal == "hold":
            return {"signal": "hold", "order": None}

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
            amount = self.account.positions.get(symbol, 0.0)

        order = self.account.execute_market_order(symbol, signal, amount, price)
        if order["status"] == "closed":
            self.store.record_trade(
                symbol, signal, amount=order["amount"], price=order["price"], order_id=order["id"],
            )
            # 买入后记录入场价和最高价
            if signal == "buy":
                self._entry_prices[symbol] = price
                self._highest_prices[symbol] = price
            elif signal == "sell":
                self._entry_prices.pop(symbol, None)
                self._highest_prices.pop(symbol, None)
            # 通知
            msg = format_trade_signal(symbol, signal, price, order["amount"], "closed", self.account.balance_usdt, self.account.positions)
            notify(msg, self.notify_file, self._queue_file)

        return {"signal": signal, "order": order}

    def run_once_from_exchange(self, exchange) -> dict:
        try:
            closes = fetch_close_prices(
                exchange,
                symbol=self.config.symbol,
                timeframe=self.config.timeframe,
                limit=max(self.config.slow_window + 1, 2),
            )
        except Exception as exc:
            msg = format_error(self.config.symbol, str(exc))
            notify(msg, self.notify_file, self._queue_file)
            return {"signal": "error", "order": None, "error": str(exc)}
        return self.on_prices(closes)

    def status(self, closes: list[float]) -> str:
        """返回当前状态摘要。"""
        price = closes[-1]
        signal = moving_average_signal(closes, fast=self.config.fast_window, slow=self.config.slow_window)
        return format_status(self.config.symbol, price, self.account.balance_usdt, self.account.positions, signal)
