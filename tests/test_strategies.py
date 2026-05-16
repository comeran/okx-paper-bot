"""Tests for okx_paper_bot.strategies module."""
import pytest
from okx_paper_bot.strategies import (
    MACrossover, MACDStrategy, RSIStrategy, BollingerStrategy,
    get_strategy, STRATEGIES, _ema, _rsi,
)


class TestEMA:
    def test_single_value(self):
        assert _ema([100.0], 10) == [100.0]

    def test_constant_values(self):
        result = _ema([100.0] * 10, 5)
        assert len(result) == 10
        assert all(abs(v - 100.0) < 0.001 for v in result)

    def test_empty(self):
        assert _ema([], 10) == []


class TestRSI:
    def test_all_gains(self):
        closes = [float(x) for x in range(100, 120)]
        rsi = _rsi(closes, 14)
        assert rsi > 90

    def test_all_losses(self):
        closes = [float(x) for x in range(120, 100, -1)]
        rsi = _rsi(closes, 14)
        assert rsi < 10

    def test_short_data(self):
        rsi = _rsi([100.0] * 5, 14)
        assert rsi == 50.0


class TestMACrossover:
    def test_hold_insufficient_data(self):
        s = MACrossover(fast=5, slow=20)
        assert s.signal([100.0] * 5) == "hold"

    def test_hold_flat(self):
        s = MACrossover(fast=5, slow=20)
        assert s.signal([100.0] * 25) == "hold"


class TestMACDStrategy:
    def test_hold_insufficient_data(self):
        s = MACDStrategy()
        assert s.signal([100.0] * 10) == "hold"

    def test_hold_flat(self):
        s = MACDStrategy()
        assert s.signal([100.0] * 50) == "hold"

    def test_returns_valid_signal(self):
        s = MACDStrategy()
        prices = [100 + i * 0.5 for i in range(50)]
        sig = s.signal(prices)
        assert sig in ("buy", "sell", "hold")


class TestRSIStrategy:
    def test_hold_insufficient_data(self):
        s = RSIStrategy()
        assert s.signal([100.0] * 5) == "hold"

    def test_returns_valid_signal(self):
        s = RSIStrategy()
        prices = [100.0 + (i % 5) * 2 for i in range(20)]
        sig = s.signal(prices)
        assert sig in ("buy", "sell", "hold")


class TestBollingerStrategy:
    def test_hold_insufficient_data(self):
        s = BollingerStrategy()
        assert s.signal([100.0] * 5) == "hold"

    def test_buy_at_lower_band(self):
        s = BollingerStrategy(period=20, std_dev=2.0)
        prices = [100.0] * 19 + [80.0]
        assert s.signal(prices) == "buy"

    def test_sell_at_upper_band(self):
        s = BollingerStrategy(period=20, std_dev=2.0)
        prices = [100.0] * 19 + [120.0]
        assert s.signal(prices) == "sell"

    def test_hold_in_middle(self):
        s = BollingerStrategy(period=20, std_dev=2.0)
        prices = [100.0 + (i % 3) * 2 for i in range(20)]
        sig = s.signal(prices)
        assert sig == "hold"


class TestGetStrategy:
    def test_all_strategies_exist(self):
        for name in STRATEGIES:
            s = get_strategy(name)
            assert hasattr(s, "signal")
            assert hasattr(s, "name")

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="未知策略"):
            get_strategy("nonexistent")

    def test_ma_crossover_custom_params(self):
        s = get_strategy("ma_crossover", fast=10, slow=30)
        assert s.fast == 10
        assert s.slow == 30
