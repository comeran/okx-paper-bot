"""Tests for okx_paper_bot.bot module."""
import pytest
from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore


class TestTradingBot:
    def _make_bot(self, tmp_path, balance=10000.0, **kwargs):
        config = BotConfig(initial_balance_usdt=balance, **kwargs)
        account = PaperAccount(balance_usdt=balance)
        store = TradeStore(tmp_path / "trades.sqlite3")
        return TradingBot(config, account, store), account, store

    def test_hold_signal(self, tmp_path):
        bot, acc, _ = self._make_bot(tmp_path)
        closes = [100.0] * 25
        result = bot.on_prices(closes)
        assert result["signal"] == "hold"
        assert result["order"] is None
        assert acc.balance_usdt == 10000.0

    def test_buy_signal(self, tmp_path):
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0,
                                         order_usdt=100, max_position_fraction=0.25)
        closes = [100.0] * 24 + [200.0]
        result = bot.on_prices(closes)
        assert result["signal"] == "buy"
        assert result["order"]["status"] == "closed"
        assert acc.balance_usdt < 10000.0
        assert "BTC/USDT" in acc.positions
        trades = store.list_trades()
        assert len(trades) == 1
        assert trades[0]["side"] == "buy"

    def test_sell_signal(self, tmp_path):
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0)
        acc.positions["BTC/USDT"] = 0.5
        closes = [100.0] * 24 + [10.0]
        result = bot.on_prices(closes)
        assert result["signal"] == "sell"
        assert result["order"]["status"] == "closed"
        assert acc.positions.get("BTC/USDT", 0.0) == 0.0
        trades = store.list_trades()
        assert len(trades) == 1
        assert trades[0]["side"] == "sell"

    def test_buy_rejected_not_recorded(self, tmp_path):
        acc = PaperAccount(balance_usdt=0.0)
        config = BotConfig()
        store = TradeStore(tmp_path / "trades.sqlite3")
        bot = TradingBot(config, acc, store)
        closes = [100.0] * 24 + [200.0]
        result = bot.on_prices(closes)
        assert result["signal"] == "buy"
        assert result["order"]["status"] == "rejected"
        assert len(store.list_trades()) == 0

    def test_run_once_from_exchange_with_fake(self, tmp_path):
        from okx_paper_bot.exchange import FakeExchange
        bot, acc, store = self._make_bot(tmp_path)
        exchange = FakeExchange(candles=[[1, 2, 3, 4, 100.0]] * 22)
        result = bot.run_once_from_exchange(exchange)
        assert "signal" in result
        assert "order" in result

    def test_run_once_from_exchange_error(self, tmp_path):
        class BrokenExchange:
            def fetch_ohlcv(self, *a, **kw):
                raise ConnectionError("network down")
        bot, _, _ = self._make_bot(tmp_path)
        result = bot.run_once_from_exchange(BrokenExchange())
        assert result["signal"] == "error"
        assert "network down" in result["error"]
