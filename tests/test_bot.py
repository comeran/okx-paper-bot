"""Tests for okx_paper_bot.bot module."""
from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore


class TestTradingBot:
    def _make_bot(self, tmp_path, balance=1000):
        config = BotConfig(symbol="BTC/USDT", fast_window=5, slow_window=20)
        account = PaperAccount(balance_usdt=balance)
        store = TradeStore(tmp_path / "trades.sqlite3")
        return TradingBot(config, account, store), account, store

    def test_hold_signal_returns_none_order(self, tmp_path):
        bot, _, _ = self._make_bot(tmp_path)
        result = bot.on_prices([100.0] * 5)
        assert result["signal"] == "hold"
        assert result["order"] is None

    def test_buy_executes_and_records(self, tmp_path):
        bot, account, store = self._make_bot(tmp_path)
        prices = [100.0] * 20 + [100.0] + [120.0] * 6
        result = bot.on_prices(prices)
        if result["signal"] == "buy":
            assert result["order"]["status"] == "closed"
            assert len(store.list_trades()) == 1
        else:
            assert result["signal"] == "hold"

    def test_run_once_from_exchange_error(self, tmp_path):
        bot, _, _ = self._make_bot(tmp_path)
        class BrokenExchange:
            def fetch_ohlcv(self, *a, **kw):
                raise ConnectionError("network down")
        result = bot.run_once_from_exchange(BrokenExchange())
        assert result["signal"] == "error"
        assert "network down" in result["error"]
