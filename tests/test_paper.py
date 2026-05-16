"""Tests for okx_paper_bot.paper module."""
import pytest
from okx_paper_bot.paper import PaperAccount


class TestPaperAccount:
    def test_initial_state(self):
        acc = PaperAccount(balance_usdt=1000.0)
        assert acc.balance_usdt == 1000.0
        assert acc.positions == {}

    def test_buy_success(self):
        acc = PaperAccount(balance_usdt=10000.0)
        order = acc.execute_market_order("BTC/USDT", "buy", 0.1, 50000.0)
        assert order["status"] == "closed"
        assert order["side"] == "buy"
        assert order["amount"] == 0.1
        assert order["price"] == 50000.0
        assert order["id"].startswith("paper-")
        assert acc.balance_usdt == 5000.0
        assert acc.positions["BTC/USDT"] == 0.1

    def test_buy_insufficient_balance(self):
        acc = PaperAccount(balance_usdt=100.0)
        order = acc.execute_market_order("BTC/USDT", "buy", 1.0, 50000.0)
        assert order["status"] == "rejected"
        assert acc.balance_usdt == 100.0
        assert acc.positions == {}

    def test_sell_success(self):
        acc = PaperAccount(balance_usdt=500.0)
        acc.positions["BTC/USDT"] = 0.2
        order = acc.execute_market_order("BTC/USDT", "sell", 0.1, 50000.0)
        assert order["status"] == "closed"
        assert acc.balance_usdt == 5500.0
        assert acc.positions["BTC/USDT"] == 0.1

    def test_sell_all_clears_position(self):
        acc = PaperAccount(balance_usdt=500.0)
        acc.positions["BTC/USDT"] = 0.1
        order = acc.execute_market_order("BTC/USDT", "sell", 0.1, 50000.0)
        assert order["status"] == "closed"
        assert acc.balance_usdt == 5500.0
        assert "BTC/USDT" not in acc.positions

    def test_sell_more_than_held(self):
        acc = PaperAccount(balance_usdt=500.0)
        acc.positions["BTC/USDT"] = 0.1
        order = acc.execute_market_order("BTC/USDT", "sell", 0.2, 50000.0)
        assert order["status"] == "rejected"
        assert acc.balance_usdt == 500.0
        assert acc.positions["BTC/USDT"] == 0.1

    def test_sell_no_position(self):
        acc = PaperAccount(balance_usdt=1000.0)
        order = acc.execute_market_order("BTC/USDT", "sell", 0.1, 50000.0)
        assert order["status"] == "rejected"

    def test_zero_amount_rejected(self):
        acc = PaperAccount(balance_usdt=1000.0)
        order = acc.execute_market_order("BTC/USDT", "buy", 0.0, 50000.0)
        assert order["status"] == "rejected"

    def test_zero_price_rejected(self):
        acc = PaperAccount(balance_usdt=1000.0)
        order = acc.execute_market_order("BTC/USDT", "buy", 0.1, 0.0)
        assert order["status"] == "rejected"

    def test_unknown_side_rejected(self):
        acc = PaperAccount(balance_usdt=1000.0)
        order = acc.execute_market_order("BTC/USDT", "hold", 0.1, 50000.0)
        assert order["status"] == "rejected"

    def test_order_ids_increment(self):
        acc = PaperAccount(balance_usdt=10000.0)
        o1 = acc.execute_market_order("BTC/USDT", "buy", 0.01, 100.0)
        o2 = acc.execute_market_order("BTC/USDT", "buy", 0.01, 100.0)
        assert o1["id"] != o2["id"]

    def test_multiple_symbols(self):
        acc = PaperAccount(balance_usdt=10000.0)
        acc.execute_market_order("BTC/USDT", "buy", 0.1, 100.0)
        acc.execute_market_order("ETH/USDT", "buy", 1.0, 100.0)
        assert acc.positions["BTC/USDT"] == 0.1
        assert acc.positions["ETH/USDT"] == 1.0
