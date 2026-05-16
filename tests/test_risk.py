"""Tests for okx_paper_bot.risk module."""
import pytest
from okx_paper_bot.risk import RiskConfig, size_order


class TestRiskConfig:
    def test_defaults(self):
        cfg = RiskConfig()
        assert cfg.order_usdt == 100.0
        assert cfg.max_position_fraction == 0.25

    def test_custom(self):
        cfg = RiskConfig(order_usdt=200, max_position_fraction=0.5)
        assert cfg.order_usdt == 200
        assert cfg.max_position_fraction == 0.5

    def test_frozen(self):
        cfg = RiskConfig()
        with pytest.raises(AttributeError):
            cfg.order_usdt = 999


class TestSizeOrder:
    def test_basic(self):
        cfg = RiskConfig(order_usdt=100, max_position_fraction=0.25)
        assert size_order(1000.0, 50.0, cfg) == 2.0

    def test_capped_by_max_position(self):
        cfg = RiskConfig(order_usdt=500, max_position_fraction=0.1)
        assert size_order(1000.0, 10.0, cfg) == 10.0

    def test_capped_by_order_usdt(self):
        cfg = RiskConfig(order_usdt=50, max_position_fraction=0.5)
        assert size_order(1000.0, 10.0, cfg) == 5.0

    def test_zero_balance(self):
        assert size_order(0.0, 100.0, RiskConfig()) == 0.0

    def test_negative_balance(self):
        assert size_order(-100.0, 100.0, RiskConfig()) == 0.0

    def test_zero_price(self):
        assert size_order(1000.0, 0.0, RiskConfig()) == 0.0

    def test_negative_price(self):
        assert size_order(1000.0, -10.0, RiskConfig()) == 0.0

    def test_fractional_result(self):
        cfg = RiskConfig(order_usdt=100, max_position_fraction=0.25)
        qty = size_order(1000.0, 30.0, cfg)
        assert abs(qty - 100.0 / 30.0) < 1e-9
