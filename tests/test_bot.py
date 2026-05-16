"""Tests for okx_paper_bot.bot module."""
import pytest
from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore


class TestTradingBot:
    def _make_bot(self, tmp_path, balance=10000.0, notify_file=None, **kwargs):
        config = BotConfig(initial_balance_usdt=balance, **kwargs)
        account = PaperAccount(balance_usdt=balance)
        store = TradeStore(tmp_path / "trades.sqlite3")
        nf = notify_file or (tmp_path / "notify.log")
        return TradingBot(config, account, store, notify_file=nf), account, store

    def test_hold_signal(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path)
        result = bot.on_prices([100.0] * 25)
        assert result["signal"] == "hold"
        assert result["order"] is None

    def test_buy_signal(self, tmp_path):
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0, order_usdt=100)
        result = bot.on_prices([100.0] * 24 + [200.0])
        assert result["signal"] == "buy"
        assert result["order"]["status"] == "closed"
        assert "BTC/USDT" in acc.positions

    def test_sell_signal(self, tmp_path):
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0)
        acc.positions["BTC/USDT"] = 0.5
        result = bot.on_prices([100.0] * 24 + [10.0])
        assert result["signal"] == "sell"
        assert result["order"]["status"] == "closed"

    def test_buy_rejected_not_recorded(self, tmp_path):
        acc = PaperAccount(balance_usdt=0.0)
        store = TradeStore(tmp_path / "trades.sqlite3")
        bot = TradingBot(BotConfig(), acc, store, notify_file=tmp_path / "nf.log")
        result = bot.on_prices([100.0] * 24 + [200.0])
        assert result["order"]["status"] == "rejected"
        assert len(store.list_trades()) == 0

    def test_run_once_from_exchange_error(self, tmp_path):
        class BrokenExchange:
            def fetch_ohlcv(self, *a, **kw): raise ConnectionError("down")
        bot, _, _ = self._make_bot(tmp_path)
        result = bot.run_once_from_exchange(BrokenExchange())
        assert result["signal"] == "error"


class TestTradingBotStopLoss:
    def _make_bot(self, tmp_path, balance=10000.0, notify_file=None, **kwargs):
        config = BotConfig(initial_balance_usdt=balance, **kwargs)
        account = PaperAccount(balance_usdt=balance)
        store = TradeStore(tmp_path / "trades.sqlite3")
        return TradingBot(config, account, store, notify_file=notify_file or tmp_path / "nf.log"), account, store

    def test_stop_loss_triggers(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, stop_loss_pct=0.05, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        entry = bot._entry_prices["BTC/USDT"]
        result = bot.on_prices([entry * 0.94] * 25)
        assert result["signal"] == "stop_loss"
        assert "BTC/USDT" not in acc.positions

    def test_take_profit_triggers(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, take_profit_pct=0.10, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        entry = bot._entry_prices["BTC/USDT"]
        result = bot.on_prices([entry * 1.12] * 25)
        assert result["signal"] == "take_profit"
        assert "BTC/USDT" not in acc.positions

    def test_no_sl_tp_within_range(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, stop_loss_pct=0.05, take_profit_pct=0.10, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        entry = bot._entry_prices["BTC/USDT"]
        result = bot.on_prices([entry * 1.02] * 25)
        assert result["signal"] == "hold"
        assert "BTC/USDT" in acc.positions

    def test_trailing_stop(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, stop_loss_pct=0.50, take_profit_pct=0.50, trailing_stop_pct=0.03, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        entry = bot._entry_prices["BTC/USDT"]
        bot.on_prices([entry * 1.20] * 25)
        assert bot._highest_prices["BTC/USDT"] == entry * 1.20
        result = bot.on_prices([entry * 1.20 * 0.96] * 25)
        assert result["signal"] == "trailing_stop"
        assert "BTC/USDT" not in acc.positions

    def test_sl_cleans_up_tracking(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, stop_loss_pct=0.05, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        assert "BTC/USDT" in bot._entry_prices
        entry = bot._entry_prices["BTC/USDT"]
        bot.on_prices([entry * 0.93] * 25)
        assert "BTC/USDT" not in bot._entry_prices

    def test_entry_price_tracked_on_buy(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, order_usdt=100)
        bot.on_prices([100.0] * 24 + [200.0])
        assert bot._entry_prices["BTC/USDT"] == 200.0
        assert bot._highest_prices["BTC/USDT"] == 200.0
