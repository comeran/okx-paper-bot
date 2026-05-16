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

    def test_buy_rejected_not_recorded(self, tmp_path):
        acc = PaperAccount(balance_usdt=0.0)
        config = BotConfig()
        store = TradeStore(tmp_path / "trades.sqlite3")
        bot = TradingBot(config, acc, store, notify_file=tmp_path / "nf.log")
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


class TestTradingBotStopLoss:
    """止损止盈集成测试。"""

    def _make_bot(self, tmp_path, balance=10000.0, notify_file=None, **kwargs):
        config = BotConfig(initial_balance_usdt=balance, **kwargs)
        account = PaperAccount(balance_usdt=balance)
        store = TradeStore(tmp_path / "trades.sqlite3")
        nf = notify_file or (tmp_path / "notify.log")
        return TradingBot(config, account, store, notify_file=nf), account, store

    def test_stop_loss_triggers(self, tmp_path):
        """价格跌破止损线 -> 自动卖出。"""
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0,
                                         stop_loss_pct=0.05, order_usdt=100)
        # 第一次调用：触发买入
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        assert "BTC/USDT" in acc.positions
        entry = bot._entry_prices["BTC/USDT"]

        # 第二次调用：价格跌6% -> 止损触发（用恒定价格避免MA交叉）
        drop_price = entry * 0.94
        sl_closes = [drop_price] * 25
        result = bot.on_prices(sl_closes)
        assert result["signal"] == "stop_loss"
        assert "BTC/USDT" not in acc.positions

    def test_take_profit_triggers(self, tmp_path):
        """价格涨过止盈线 -> 自动卖出。"""
        bot, acc, store = self._make_bot(tmp_path, balance=10000.0,
                                         take_profit_pct=0.10, order_usdt=100)
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        entry = bot._entry_prices["BTC/USDT"]

        # 价格涨12% -> 止盈触发
        tp_price = entry * 1.12
        tp_closes = [tp_price] * 25
        result = bot.on_prices(tp_closes)
        assert result["signal"] == "take_profit"
        assert "BTC/USDT" not in acc.positions

    def test_no_sl_tp_within_range(self, tmp_path):
        """价格在止损止盈范围内 + 无MA交叉 -> hold。"""
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0,
                                     stop_loss_pct=0.05, take_profit_pct=0.10, order_usdt=100)
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        entry = bot._entry_prices["BTC/USDT"]

        # 价格变动2%，用恒定价格避免MA交叉
        normal_price = entry * 1.02
        normal_closes = [normal_price] * 25
        result = bot.on_prices(normal_closes)
        assert result["signal"] == "hold"
        assert "BTC/USDT" in acc.positions

    def test_trailing_stop(self, tmp_path):
        """移动止损：从最高点回撤触发。"""
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0,
                                     stop_loss_pct=0.50, take_profit_pct=0.50,
                                     trailing_stop_pct=0.03, order_usdt=100)
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        entry = bot._entry_prices["BTC/USDT"]

        # 价格涨到120% -> 更新最高价（恒定价格避免MA交叉）
        up_price = entry * 1.20
        up_closes = [up_price] * 25
        bot.on_prices(up_closes)
        assert bot._highest_prices["BTC/USDT"] == entry * 1.20

        # 从最高点回撤4% -> 触发移动止损
        trail_price = entry * 1.20 * 0.96
        trail_closes = [trail_price] * 25
        result = bot.on_prices(trail_closes)
        assert result["signal"] == "trailing_stop"
        assert "BTC/USDT" not in acc.positions

    def test_sl_cleans_up_tracking(self, tmp_path):
        """止损后清除入场价和最高价跟踪。"""
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0,
                                     stop_loss_pct=0.05, order_usdt=100)
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        assert "BTC/USDT" in bot._entry_prices

        entry = bot._entry_prices["BTC/USDT"]
        sl_closes = [entry * 0.93] * 25
        bot.on_prices(sl_closes)
        assert "BTC/USDT" not in bot._entry_prices
        assert "BTC/USDT" not in bot._highest_prices

    def test_entry_price_tracked_on_buy(self, tmp_path):
        """买入后应记录入场价和最高价。"""
        bot, acc, _ = self._make_bot(tmp_path, balance=10000.0, order_usdt=100)
        buy_closes = [100.0] * 24 + [200.0]
        bot.on_prices(buy_closes)
        assert bot._entry_prices["BTC/USDT"] == 200.0
        assert bot._highest_prices["BTC/USDT"] == 200.0
