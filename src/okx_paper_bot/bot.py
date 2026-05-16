from __future__ import annotations

from pathlib import Path

from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.risk import RiskConfig, StopLossConfig, size_order, check_stop_loss
from okx_paper_bot.store import TradeStore
from okx_paper_bot.strategy import get_signal
from okx_paper_bot.exchange import fetch_close_prices
from okx_paper_bot.notify import notify, format_trade_signal, format_error, format_status


class TradingBot:
    def __init__(self, config: BotConfig, account: PaperAccount, store: TradeStore,
                 notify_file: Path | str | None = None):
        self.config = config
        self.account = account
        self.store = store
        self.notify_file = notify_file or config.notify_file
        self._queue_file = Path("data/notify_queue.jsonl")
        self._entry_prices: dict[str, float] = {}
        self._highest_prices: dict[str, float] = {}

    def _get_signal(self, closes: list[float]) -> str:
        cfg = self.config
        return get_signal(closes, strategy=cfg.strategy_name,
                          fast=cfg.fast_window, slow=cfg.slow_window,
                          period=cfg.rsi_period, buy_threshold=cfg.rsi_buy,
                          sell_threshold=cfg.rsi_sell,
                          num_std=cfg.bollinger_std)

    def on_prices(self, closes: list[float], symbol: str | None = None) -> dict:
        price = closes[-1]
        sym = symbol or self.config.symbol

        # 1. 检查限价单触发
        filled = self.account.check_pending_orders(sym, price)
        for f in filled:
            if f["status"] == "closed":
                self.store.record_trade(sym, f["side"], amount=f["amount"], price=f["price"], order_id=f["id"])
                msg = format_trade_signal(sym, f"limit_{f['side']}", f["price"], f["amount"], "closed",
                                          self.account.balance_usdt, self.account.positions)
                notify(msg, self.notify_file, self._queue_file)

        # 2. 止损止盈
        held = self.account.positions.get(sym, 0.0)
        if held > 0 and sym in self._entry_prices:
            if price > self._highest_prices.get(sym, 0):
                self._highest_prices[sym] = price
            sl_config = StopLossConfig(stop_loss_pct=self.config.stop_loss_pct,
                                       take_profit_pct=self.config.take_profit_pct,
                                       trailing_stop_pct=self.config.trailing_stop_pct)
            trigger = check_stop_loss(self._entry_prices[sym], price,
                                      self._highest_prices.get(sym, price), sl_config)
            if trigger:
                order = self.account.execute_market_order(sym, "sell", held, price)
                if order["status"] == "closed":
                    self.store.record_trade(sym, "sell", amount=order["amount"], price=order["price"], order_id=order["id"])
                    pnl = (price - self._entry_prices[sym]) * held
                    reason = f"{trigger} 触发, 盈亏: {pnl:+.2f} USDT"
                    msg = format_trade_signal(sym, trigger, price, order["amount"], "closed",
                                              self.account.balance_usdt, self.account.positions, reason=reason)
                    notify(msg, self.notify_file, self._queue_file)
                    self._entry_prices.pop(sym, None)
                    self._highest_prices.pop(sym, None)
                    return {"signal": trigger, "order": order, "reason": reason}
                return {"signal": trigger, "order": order}

        # 3. 策略信号
        signal = self._get_signal(closes)
        if signal == "hold":
            return {"signal": "hold", "order": None}

        if signal == "buy":
            amount = size_order(self.account.balance_usdt, price,
                                RiskConfig(order_usdt=self.config.order_usdt,
                                           max_position_fraction=self.config.max_position_fraction))
        else:
            amount = self.account.positions.get(sym, 0.0)

        order = self.account.execute_market_order(sym, signal, amount, price)
        if order["status"] == "closed":
            self.store.record_trade(sym, signal, amount=order["amount"], price=order["price"], order_id=order["id"])
            if signal == "buy":
                self._entry_prices[sym] = price
                self._highest_prices[sym] = price
            elif signal == "sell":
                self._entry_prices.pop(sym, None)
                self._highest_prices.pop(sym, None)
            msg = format_trade_signal(sym, signal, price, order["amount"], "closed",
                                      self.account.balance_usdt, self.account.positions)
            notify(msg, self.notify_file, self._queue_file)

        return {"signal": signal, "order": order}

    def run_once_from_exchange(self, exchange, symbol: str | None = None) -> dict:
        sym = symbol or self.config.symbol
        try:
            closes = fetch_close_prices(exchange, symbol=sym, timeframe=self.config.timeframe,
                                        limit=max(self.config.slow_window + 1, 22))
        except Exception as exc:
            msg = format_error(sym, str(exc))
            notify(msg, self.notify_file, self._queue_file)
            return {"signal": "error", "order": None, "error": str(exc)}
        return self.on_prices(closes, symbol=sym)

    def status(self, closes: list[float], symbol: str | None = None) -> str:
        price = closes[-1]
        sym = symbol or self.config.symbol
        signal = self._get_signal(closes)
        return format_status(sym, price, self.account.balance_usdt, self.account.positions, signal)
