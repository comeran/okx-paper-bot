"""Tests for paper."""
import pytest
from okx_paper_bot.paper import PaperAccount

class TestPaperAccount:
    def test_initial(self): a = PaperAccount(1000.0); assert a.balance_usdt == 1000.0
    def test_buy_fee(self):
        a = PaperAccount(10000.0, fee_pct=0.001, slippage_pct=0.0)
        o = a.execute_market_order("BTC/USDT", "buy", 0.1, 50000.0)
        assert o["status"] == "closed" and o["fee"] == 5.0 and a.balance_usdt == 4995.0
    def test_sell_slippage(self):
        a = PaperAccount(500.0, fee_pct=0.0, slippage_pct=0.001)
        a.positions["BTC/USDT"] = 0.2
        o = a.execute_market_order("BTC/USDT", "sell", 0.1, 50000.0)
        assert o["status"] == "closed" and o["price"] < 50000.0
    def test_insufficient(self):
        assert PaperAccount(100.0).execute_market_order("BTC/USDT", "buy", 1.0, 50000.0)["status"] == "rejected"
    def test_sell_all(self):
        a = PaperAccount(500.0); a.positions["BTC/USDT"] = 0.1
        a.execute_market_order("BTC/USDT", "sell", 0.1, 50000.0)
        assert "BTC/USDT" not in a.positions
    def test_limit(self):
        a = PaperAccount(10000.0)
        o = a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        assert o["status"] == "pending" and len(a._pending_orders) == 1
    def test_limit_fill(self):
        a = PaperAccount(10000.0, fee_pct=0.0, slippage_pct=0.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        f = a.check_pending_orders("BTC/USDT", 47000.0)
        assert len(f) == 1 and f[0]["status"] == "closed"
    def test_limit_not_fill(self):
        a = PaperAccount(10000.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        assert len(a.check_pending_orders("BTC/USDT", 50000.0)) == 0
    def test_cancel(self):
        a = PaperAccount(10000.0)
        a.place_limit_order("BTC/USDT", "buy", 0.1, 48000.0)
        a.place_limit_order("ETH/USDT", "buy", 1.0, 3000.0)
        assert a.cancel_all_pending("BTC/USDT") == 1 and len(a._pending_orders) == 1
    def test_zero(self):
        assert PaperAccount(1000.0).execute_market_order("BTC/USDT", "buy", 0.0, 50000.0)["status"] == "rejected"
