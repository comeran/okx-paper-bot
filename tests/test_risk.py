"""Tests for okx_paper_bot.risk module."""
import pytest
from okx_paper_bot.risk import RiskConfig, StopLossConfig, size_order, check_stop_loss


class TestRiskConfig:
    def test_defaults(self):
        assert RiskConfig().order_usdt == 100.0
    def test_frozen(self):
        with pytest.raises(AttributeError):
            RiskConfig().order_usdt = 999


class TestSizeOrder:
    def test_basic(self):
        assert size_order(1000.0, 50.0, RiskConfig(order_usdt=100, max_position_fraction=0.25)) == 2.0
    def test_zero_price(self):
        assert size_order(1000.0, 0.0, RiskConfig()) == 0.0
    def test_zero_balance(self):
        assert size_order(0.0, 100.0, RiskConfig()) == 0.0


class TestStopLossConfig:
    def test_defaults(self):
        cfg = StopLossConfig()
        assert cfg.stop_loss_pct == 0.05
        assert cfg.take_profit_pct == 0.10
        assert cfg.trailing_stop_pct == 0.0


class TestCheckStopLoss:
    def test_stop_loss_triggered(self):
        assert check_stop_loss(100.0, 94.0, 100.0, StopLossConfig(stop_loss_pct=0.05)) == "stop_loss"
    def test_stop_loss_not_triggered(self):
        assert check_stop_loss(100.0, 96.0, 100.0, StopLossConfig(stop_loss_pct=0.05)) is None
    def test_take_profit_triggered(self):
        assert check_stop_loss(100.0, 111.0, 111.0, StopLossConfig(take_profit_pct=0.10)) == "take_profit"
    def test_take_profit_not_triggered(self):
        assert check_stop_loss(100.0, 109.0, 109.0, StopLossConfig(take_profit_pct=0.10)) is None
    def test_trailing_stop_triggered(self):
        cfg = StopLossConfig(stop_loss_pct=0.50, take_profit_pct=0.50, trailing_stop_pct=0.03)
        assert check_stop_loss(100.0, 116.0, 120.0, cfg) == "trailing_stop"
    def test_trailing_stop_not_triggered(self):
        cfg = StopLossConfig(stop_loss_pct=0.50, take_profit_pct=0.50, trailing_stop_pct=0.03)
        assert check_stop_loss(100.0, 117.0, 120.0, cfg) is None
    def test_trailing_stop_disabled(self):
        cfg = StopLossConfig(stop_loss_pct=0.50, take_profit_pct=0.50, trailing_stop_pct=0.0)
        assert check_stop_loss(100.0, 80.0, 120.0, cfg) is None
    def test_zero_prices(self):
        assert check_stop_loss(0.0, 100.0, 100.0, StopLossConfig()) is None
    def test_priority_stop_loss(self):
        cfg = StopLossConfig(stop_loss_pct=0.05, take_profit_pct=0.10)
        assert check_stop_loss(100.0, 90.0, 100.0, cfg) == "stop_loss"
