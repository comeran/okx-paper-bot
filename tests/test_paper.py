"""Tests for okx_paper_bot.paper module."""
from okx_paper_bot.paper import PaperAccount


class TestPaperAccount:
    def test_buy_reduces_balance(self):
        acc = PaperAccount(balance_usdt=1000)
        order = acc.execute_market_order("BTC/USDT", "buy", 0.01, 50000)
        assert order["status"] == "closed"
        assert acc.balance_usdt == 500.0
        assert acc.positions["BTC/USDT"] == 0.01

    def test_sell_increases_balance(self):
        acc = PaperAccount(balance_usdt=500, positions={"BTC/USDT": 0.02})
        order = acc.execute_market_order("BTC/USDT", "sell", 0.01, 50000)
        assert order["status"] == "closed"
        assert acc.balance_usdt == 1000.0
        assert acc.positions["BTC/USDT"] == 0.01

    def test_sell_all_removes_position(self):
        acc = PaperAccount(balance_usdt=500, positions={"BTC/USDT": 0.01})
        acc.execute_market_order("BTC/USDT", "sell", 0.01, 50000)
        assert "BTC/USDT" not in acc.positions

    def test_buy_insufficient_balance_rejected(self):
        acc = PaperAccount(balance_usdt=100)
        order = acc.execute_market_order("BTC/USDT", "buy", 1.0, 50000)
        assert order["status"] == "rejected"
        assert acc.balance_usdt == 100

    def test_sell_more_than_held_rejected(self):
        acc = PaperAccount(balance_usdt=500, positions={"BTC/USDT": 0.01})
        order = acc.execute_market_order("BTC/USDT", "sell", 0.02, 50000)
        assert order["status"] == "rejected"

    def test_zero_amount_rejected(self):
        acc = PaperAccount(balance_usdt=1000)
        order = acc.execute_market_order("BTC/USDT", "buy", 0, 50000)
        assert order["status"] == "rejected"

    def test_negative_price_rejected(self):
        acc = PaperAccount(balance_usdt=1000)
        order = acc.execute_market_order("BTC/USDT", "buy", 1.0, -1)
        assert order["status"] == "rejected"

    def test_unknown_side_rejected(self):
        acc = PaperAccount(balance_usdt=1000)
        order = acc.execute_market_order("BTC/USDT", "hold", 1.0, 50000)
        assert order["status"] == "rejected"

    def test_order_has_id(self):
        acc = PaperAccount(balance_usdt=1000)
        order = acc.execute_market_order("BTC/USDT", "buy", 0.01, 50000)
        assert order["id"].startswith("paper-")
