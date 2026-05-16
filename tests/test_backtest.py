"""Tests for okx_paper_bot.backtest and backtester modules."""
import pytest
from okx_paper_bot.backtest import BacktestResult, BacktestTrade
from okx_paper_bot.backtester import run_backtest
from okx_paper_bot.config import BotConfig


class TestBacktestResult:
    def _make_result(self, trades=None, initial=10000, final=10500):
        return BacktestResult(
            symbol="BTC/USDT", timeframe="1h",
            start_time="2025-01-01", end_time="2025-01-31",
            initial_balance=initial, final_balance=final,
            trades=trades or [],
        )

    def test_total_return(self):
        r = self._make_result(initial=10000, final=11000)
        assert r.total_return == 0.1

    def test_win_rate(self):
        trades = [
            BacktestTrade(entry_time="", entry_price=100, exit_price=110, pnl=10),
            BacktestTrade(entry_time="", entry_price=100, exit_price=90, pnl=-10),
            BacktestTrade(entry_time="", entry_price=100, exit_price=120, pnl=20),
        ]
        r = self._make_result(trades=trades)
        assert r.total_trades == 3
        assert r.winning_trades == 2
        assert r.losing_trades == 1
        assert abs(r.win_rate - 2 / 3) < 0.001

    def test_profit_factor(self):
        trades = [
            BacktestTrade(entry_time="", entry_price=100, exit_price=110, pnl=100),
            BacktestTrade(entry_time="", entry_price=100, exit_price=90, pnl=-50),
        ]
        r = self._make_result(trades=trades)
        assert r.profit_factor == 2.0

    def test_max_drawdown(self):
        trades = [
            BacktestTrade(entry_time="", entry_price=100, exit_price=110, pnl=1000),
            BacktestTrade(entry_time="", entry_price=110, exit_price=90, pnl=-2000),
            BacktestTrade(entry_time="", entry_price=90, exit_price=100, pnl=1000),
        ]
        r = self._make_result(trades=trades, initial=10000, final=10000)
        dd = r.max_drawdown
        assert dd > 0.18
        assert dd < 0.19

    def test_no_trades(self):
        r = self._make_result()
        assert r.total_trades == 0
        assert r.win_rate == 0.0
        assert r.max_drawdown == 0.0

    def test_summary_contains_key_info(self):
        trades = [BacktestTrade(entry_time="", entry_price=100, exit_price=110, pnl=100)]
        r = self._make_result(trades=trades, initial=10000, final=10100)
        s = r.summary()
        assert "BTC/USDT" in s
        assert "10000" in s
        assert "10100" in s


class TestRunBacktest:
    def _generate_candles(self, prices, start_ts=1700000000000, interval_ms=3600000):
        candles = []
        for i, p in enumerate(prices):
            ts = start_ts + i * interval_ms
            candles.append([ts, p, p + 1, p - 1, p, 1000])
        return candles

    def test_basic_backtest(self):
        prices = [100.0] * 24 + [120.0]
        candles = self._generate_candles(prices)
        config = BotConfig(symbol="BTC/USDT", fast_window=5, slow_window=20,
                          initial_balance_usdt=10000, order_usdt=500)
        result = run_backtest(candles, config)
        assert result.total_trades >= 0
        assert result.final_balance > 0

    def test_insufficient_data_raises(self):
        candles = self._generate_candles([100.0] * 5)
        config = BotConfig(slow_window=20)
        with pytest.raises(ValueError, match="K 线"):
            run_backtest(candles, config)

    def test_no_trades_flat_market(self):
        prices = [100.0] * 50
        candles = self._generate_candles(prices)
        config = BotConfig(symbol="BTC/USDT", fast_window=5, slow_window=20,
                          initial_balance_usdt=10000, order_usdt=500)
        result = run_backtest(candles, config)
        assert result.total_trades == 0
        assert result.final_balance == 10000
