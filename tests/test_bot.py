"""Tests for bot."""
import pytest
from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore

class TestTradingBot:
    def _make(self, tmp_path, balance=10000.0, **kw):
        c = BotConfig(initial_balance_usdt=balance, **kw)
        a = PaperAccount(balance_usdt=balance, fee_pct=0.0, slippage_pct=0.0)
        s = TradeStore(tmp_path / "t.sqlite3")
        return TradingBot(c, a, s, notify_file=tmp_path / "nf.log"), a, s
    def test_hold(self, tmp_path):
        bot, _, _ = self._make(tmp_path)
        assert bot.on_prices([100.0]*25)["signal"] == "hold"
    def test_buy(self, tmp_path):
        bot, acc, _ = self._make(tmp_path, order_usdt=100)
        r = bot.on_prices([100.0]*24+[200.0])
        assert r["signal"] == "buy" and r["order"]["status"] == "closed"
    def test_sell(self, tmp_path):
        bot, acc, _ = self._make(tmp_path)
        acc.positions["BTC/USDT"] = 0.5
        r = bot.on_prices([100.0]*24+[10.0])
        assert r["signal"] == "sell" and r["order"]["status"] == "closed"
    def test_rsi(self, tmp_path):
        bot, _, _ = self._make(tmp_path, strategy_name="rsi")
        assert bot.on_prices([100.0]*25)["signal"] == "hold"
    def test_bollinger(self, tmp_path):
        bot, _, _ = self._make(tmp_path, strategy_name="bollinger")
        assert bot.on_prices([100.0]*25)["signal"] == "hold"
    def test_multi_symbol(self, tmp_path):
        bot, acc, _ = self._make(tmp_path, order_usdt=100)
        bot.on_prices([100.0]*24+[200.0], symbol="BTC/USDT")
        bot.on_prices([100.0]*24+[200.0], symbol="ETH/USDT")
        assert "BTC/USDT" in acc.positions and "ETH/USDT" in acc.positions

class TestBotStopLoss:
    def _make(self, tmp_path, balance=10000.0, **kw):
        c = BotConfig(initial_balance_usdt=balance, **kw)
        a = PaperAccount(balance_usdt=balance, fee_pct=0.0, slippage_pct=0.0)
        s = TradeStore(tmp_path / "t.sqlite3")
        return TradingBot(c, a, s, notify_file=tmp_path / "nf.log"), a, s
    def test_sl(self, tmp_path):
        bot, acc, _ = self._make(tmp_path, stop_loss_pct=0.05, order_usdt=100)
        bot.on_prices([100.0]*24+[200.0])
        e = bot._entry_prices["BTC/USDT"]
        r = bot.on_prices([e*0.94]*25)
        assert r["signal"] == "stop_loss" and "BTC/USDT" not in acc.positions
    def test_tp(self, tmp_path):
        bot, acc, _ = self._make(tmp_path, take_profit_pct=0.10, order_usdt=100)
        bot.on_prices([100.0]*24+[200.0])
        e = bot._entry_prices["BTC/USDT"]
        r = bot.on_prices([e*1.12]*25)
        assert r["signal"] == "take_profit" and "BTC/USDT" not in acc.positions
    def test_trailing(self, tmp_path):
        bot, acc, _ = self._make(tmp_path, stop_loss_pct=0.50, take_profit_pct=0.50, trailing_stop_pct=0.03, order_usdt=100)
        bot.on_prices([100.0]*24+[200.0])
        e = bot._entry_prices["BTC/USDT"]
        bot.on_prices([e*1.20]*25)
        r = bot.on_prices([e*1.20*0.96]*25)
        assert r["signal"] == "trailing_stop"
