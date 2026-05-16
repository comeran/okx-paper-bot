"""Tests for risk."""
import pytest
from okx_paper_bot.risk import RiskConfig, StopLossConfig, size_order, check_stop_loss

class TestRiskConfig:
    def test_defaults(self): assert RiskConfig().order_usdt == 100.0
    def test_frozen(self):
        with pytest.raises(AttributeError): RiskConfig().order_usdt = 999

class TestSizeOrder:
    def test_basic(self): assert size_order(1000.0, 50.0, RiskConfig(order_usdt=100, max_position_fraction=0.25)) == 2.0
    def test_zero(self): assert size_order(0.0, 0.0, RiskConfig()) == 0.0

class TestStopLossConfig:
    def test_defaults(self): c = StopLossConfig(); assert c.stop_loss_pct == 0.05

class TestCheckStopLoss:
    def test_sl(self): assert check_stop_loss(100.0, 94.0, 100.0, StopLossConfig(stop_loss_pct=0.05)) == "stop_loss"
    def test_tp(self): assert check_stop_loss(100.0, 111.0, 111.0, StopLossConfig(take_profit_pct=0.10)) == "take_profit"
    def test_trailing(self): assert check_stop_loss(100.0, 116.0, 120.0, StopLossConfig(stop_loss_pct=0.5, take_profit_pct=0.5, trailing_stop_pct=0.03)) == "trailing_stop"
    def test_none(self): assert check_stop_loss(100.0, 96.0, 100.0, StopLossConfig(stop_loss_pct=0.05)) is None
