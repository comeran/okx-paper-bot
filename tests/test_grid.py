"""Tests for okx_paper_bot.grid module."""
from okx_paper_bot.grid import GridConfig, GridLevel, GridState


class TestGridConfig:
    def test_grid_step(self):
        c = GridConfig(lower_price=100, upper_price=200, grid_count=10)
        assert c.grid_step == 10.0

    def test_grid_prices(self):
        c = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        prices = c.grid_prices()
        assert len(prices) == 5
        assert prices[0] == 100.0
        assert prices[-1] == 200.0
        assert prices[2] == 150.0


class TestGridState:
    def test_initial_state(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        state = GridState(config=cfg)
        assert len(state.levels) == 5
        assert state.total_profit == 0.0
        assert state.completed_grids == 0

    def test_buy_signal(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        state = GridState(config=cfg)
        # 价格从 160 跌到 140，穿过 150 网格线
        signals = state.check_signals(current_price=140, prev_price=160)
        assert len(signals) >= 1
        assert any(s["action"] == "buy" and s["price"] == 150.0 for s in signals)

    def test_sell_signal_after_buy(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        state = GridState(config=cfg)
        # 先标记 150 买入成交
        state.mark_buy_filled(2, "order-1")
        # 价格从 140 涨到 160，穿过 150
        signals = state.check_signals(current_price=160, prev_price=140)
        assert any(s["action"] == "sell" and s["price"] == 150.0 for s in signals)

    def test_no_duplicate_buy(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        state = GridState(config=cfg)
        state.mark_buy_filled(2, "order-1")
        # 再次穿过同一网格，不应触发
        signals = state.check_signals(current_price=140, prev_price=160)
        assert not any(s["level_idx"] == 2 for s in signals)

    def test_completed_grids(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4, order_usdt=1000)
        state = GridState(config=cfg)
        state.mark_buy_filled(2, "buy-1")
        state.mark_sell_filled(2, "sell-1")
        assert state.completed_grids == 1
        assert state.total_profit > 0

    def test_status(self):
        cfg = GridConfig(lower_price=100, upper_price=200, grid_count=4)
        state = GridState(config=cfg)
        s = state.status()
        assert "BTC/USDT" in s
        assert "100" in s
        assert "200" in s
