"""Tests for okx_paper_bot.strategy module."""
import pytest
from okx_paper_bot.strategy import sma, moving_average_signal


class TestSMA:
    def test_basic(self):
        assert sma([1, 2, 3, 4, 5], 3) == 4.0
    def test_window_equals_length(self):
        assert sma([10, 20, 30], 3) == 20.0
    def test_single_value(self):
        assert sma([42.0], 1) == 42.0
    def test_window_zero_raises(self):
        with pytest.raises(ValueError, match="window must be positive"):
            sma([1, 2, 3], 0)
    def test_window_negative_raises(self):
        with pytest.raises(ValueError, match="window must be positive"):
            sma([1, 2, 3], -1)
    def test_not_enough_values(self):
        with pytest.raises(ValueError, match="not enough values"):
            sma([1, 2], 3)
    def test_uses_last_n_values(self):
        assert sma([100, 1, 2, 3], 3) == 2.0


class TestMovingAverageSignal:
    def test_hold_when_insufficient_data(self):
        assert moving_average_signal([1, 2, 3, 4, 5], fast=5, slow=20) == "hold"
    def test_hold_when_flat(self):
        assert moving_average_signal([100.0] * 25, fast=5, slow=20) == "hold"
    def test_buy_crossover(self):
        assert moving_average_signal([100.0] * 24 + [200.0], fast=5, slow=20) == "buy"
    def test_sell_crossover(self):
        assert moving_average_signal([100.0] * 24 + [10.0], fast=5, slow=20) == "sell"
    def test_invalid_fast_zero(self):
        with pytest.raises(ValueError, match="require 0 < fast < slow"):
            moving_average_signal([1.0] * 25, fast=0, slow=20)
    def test_invalid_fast_equals_slow(self):
        with pytest.raises(ValueError, match="require 0 < fast < slow"):
            moving_average_signal([1.0] * 25, fast=10, slow=10)
    def test_invalid_fast_greater_than_slow(self):
        with pytest.raises(ValueError, match="require 0 < fast < slow"):
            moving_average_signal([1.0] * 25, fast=20, slow=10)
