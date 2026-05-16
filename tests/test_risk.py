"""Tests for okx_paper_bot.risk module (updated with stop-loss/take-profit)."""
import dataclasses

from okx_paper_bot.risk import RiskConfig, StopLossConfig, size_order, check_stop_loss


class TestSizeOrder:
    def _default_config(self):
        return RiskConfig()

    def test_normal_sizing(self):
        assert size_order(balance_usdt=1000, price=50.0, config=self._default_config()) == 2.0

    def test_capped_by_balance_fraction(self):
        result = size_order(100, 50.0, self._default_config())
        assert result == 0.5

    def test_zero_price_returns_zero(self):
        assert size_order(1000, 0.0, self._default_config()) == 0.0

    def test_negative_price_returns_zero(self):
        assert size_order(1000, -10.0, self._default_config()) == 0.0

    def test_zero_balance_returns_zero(self):
        assert size_order(0, 50.0, self._default_config()) == 0.0

    def test_custom_config(self):
        config = RiskConfig(order_usdt=200, max_position_fraction=0.5)
        assert size_order(1000, 100.0, config) == 2.0


class TestRiskConfig:
    def test_defaults(self):
        c = RiskConfig()
        assert c.order_usdt == 100.0
        assert c.max_position_fraction == 0.25

    def test_frozen(self):
        c = RiskConfig()
        assert dataclasses.is_dataclass(c)
        try:
            c.order_usdt = 999
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestStopLossConfig:
    def test_defaults(self):
        c = StopLossConfig()
        assert c.stop_loss_pct == 0.05
        assert c.take_profit_pct == 0.10
        assert c.trailing_stop_pct == 0.0

    def test_custom(self):
        c = StopLossConfig(stop_loss_pct=0.03, take_profit_pct=0.20, trailing_stop_pct=0.05)
        assert c.stop_loss_pct == 0.03


class TestCheckStopLoss:
    def test_no_trigger(self):
        config = StopLossConfig(stop_loss_pct=0.05, take_profit_pct=0.10)
        assert check_stop_loss(100, 102, 102, config) is None

    def test_stop_loss_triggered(self):
        config = StopLossConfig(stop_loss_pct=0.05)
        assert check_stop_loss(100, 94, 100, config) == "stop_loss"

    def test_stop_loss_boundary(self):
        config = StopLossConfig(stop_loss_pct=0.05)
        assert check_stop_loss(100, 95, 100, config) == "stop_loss"
        assert check_stop_loss(100, 95.1, 100, config) is None

    def test_take_profit_triggered(self):
        config = StopLossConfig(take_profit_pct=0.10)
        assert check_stop_loss(100, 111, 111, config) == "take_profit"

    def test_take_profit_boundary(self):
        config = StopLossConfig(take_profit_pct=0.10)
        # 100 * 1.10 = 110.0, >= should trigger
        assert check_stop_loss(100, 110.01, 110.01, config) == "take_profit"
        assert check_stop_loss(100, 109.9, 109.9, config) is None

    def test_trailing_stop_triggered(self):
        # 关掉 take_profit，只测 trailing_stop
        config = StopLossConfig(stop_loss_pct=0.05, take_profit_pct=999, trailing_stop_pct=0.03)
        # 入场 100, 最高 120, 当前 116 → 从高点回撤 3.3% > 3%
        assert check_stop_loss(100, 116, 120, config) == "trailing_stop"

    def test_trailing_stop_no_trigger(self):
        config = StopLossConfig(stop_loss_pct=0.05, take_profit_pct=999, trailing_stop_pct=0.03)
        # 最高 120, 当前 117 → 回撤 2.5% < 3%
        assert check_stop_loss(100, 117, 120, config) is None

    def test_trailing_stop_disabled(self):
        config = StopLossConfig(trailing_stop_pct=0.0)
        assert check_stop_loss(100, 100, 120, config) is None

    def test_zero_prices(self):
        config = StopLossConfig()
        assert check_stop_loss(0, 100, 100, config) is None
        assert check_stop_loss(100, 0, 100, config) is None
