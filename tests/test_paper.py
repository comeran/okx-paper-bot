"""Tests for paper - multi-position + partial TP + fees + limit orders."""
import pytest
from okx_paper_bot.paper import PaperAccount, Position

class TestMultiPosition:
    def test_multiple_buys(self):
        a = PaperAccount(100000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 0.1, 50000.0)
        a.execute_market_order("BTC/USDT", "buy", 0.2, 60000.0)
        assert a.total_held("BTC/USDT") == pytest.approx(0.3)
        assert len(a.get_positions("BTC/USDT")) == 2
    def test_avg_entry_price(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
        a.execute_market_order("BTC/USDT", "buy", 1.0, 200.0)
        assert a.avg_entry_price("BTC/USDT") == pytest.approx(150.0)
    def test_fifo_sell(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 0.5, 100.0)
        a.execute_market_order("BTC/USDT", "buy", 0.5, 200.0)
        a.execute_market_order("BTC/USDT", "sell", 0.3, 150.0)
        positions = a.get_positions("BTC/USDT")
        assert len(positions) == 2
        assert positions[0].amount == pytest.approx(0.2)  # first lot reduced
        assert positions[1].amount == pytest.approx(0.5)  # second lot untouched
    def test_sell_all(self):
        a = PaperAccount(500.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 0.1, 5000.0)
        a.execute_market_order("BTC/USDT", "sell", 0.1, 5000.0)
        assert a.total_held("BTC/USDT") == 0.0
    def test_multi_symbol(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 0.1, 50000.0)
        a.execute_market_order("ETH/USDT", "buy", 1.0, 3000.0)
        assert a.total_held("BTC/USDT") == 0.1
        assert a.total_held("ETH/USDT") == 1.0

class TestPartialTP:
    def test_close_partial_half(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
        orders = a.close_partial("BTC/USDT", 0.5, 120.0)
        assert len(orders) == 1
        assert orders[0]["status"] == "closed"
        assert a.total_held("BTC/USDT") == pytest.approx(0.5)
    def test_close_partial_all(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
        a.close_partial("BTC/USDT", 1.0, 120.0)
        assert a.total_held("BTC/USDT") == 0.0
    def test_close_partial_multiple_lots(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.execute_market_order("BTC/USDT", "buy", 0.5, 100.0)
        a.execute_market_order("BTC/USDT", "buy", 0.5, 200.0)
        orders = a.close_partial("BTC/USDT", 0.5, 150.0)
        assert len(orders) == 2
        assert a.total_held("BTC/USDT") == pytest.approx(0.5)
    def test_close_partial_empty(self):
        a = PaperAccount(10000.0)
        assert a.close_partial("BTC/USDT", 0.5, 100.0) == []

class TestFeeSlippage:
    def test_fee(self):
        a = PaperAccount(10000.0, fee_pct=0.001, slippage_pct=0.0)
        o = a.execute_market_order("BTC/USDT", "buy", 0.1, 50000.0)
        assert o["fee"] == pytest.approx(5.0)
    def test_slippage(self):
        a = PaperAccount(500.0, fee_pct=0.0, slippage_pct=0.01)
        a.positions  # just access
        a.execute_market_order("BTC/USDT", "buy", 0.1, 100.0)
        assert a.get_positions("BTC/USDT")[0].entry_price > 100.0

class TestLimitOrders:
    def test_place_and_fill(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        filled = a.check_pending_orders("BTC/USDT", 47000.0)
        assert len(filled) == 1 and filled[0]["status"] == "closed"
    def test_not_fill(self):
        a = PaperAccount(10000.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        assert len(a.check_pending_orders("BTC/USDT", 50000.0)) == 0
    def test_cancel(self):
        a = PaperAccount(10000.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        assert a.cancel_all_pending("BTC/USDT") == 1
    def test_reject_zero(self):
        a = PaperAccount(10000.0)
        assert a.execute_market_order("BTC/USDT", "buy", 0.0, 100.0)["status"] == "rejected"
