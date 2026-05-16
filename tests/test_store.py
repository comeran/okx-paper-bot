"""Tests for okx_paper_bot.store module."""
import pytest
from okx_paper_bot.store import TradeStore


class TestTradeStore:
    def test_init_creates_db(self, tmp_path):
        db_path = tmp_path / "trades.sqlite3"
        store = TradeStore(db_path)
        assert db_path.exists()

    def test_record_and_list(self, tmp_path):
        db_path = tmp_path / "trades.sqlite3"
        store = TradeStore(db_path)
        store.record_trade("BTC/USDT", "buy", 0.1, 50000.0, "paper-1")
        trades = store.list_trades()
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "BTC/USDT"
        assert t["side"] == "buy"
        assert t["amount"] == 0.1
        assert t["price"] == 50000.0
        assert t["order_id"] == "paper-1"

    def test_multiple_trades_ordered(self, tmp_path):
        db_path = tmp_path / "trades.sqlite3"
        store = TradeStore(db_path)
        store.record_trade("BTC/USDT", "buy", 0.1, 50000.0, "paper-1")
        store.record_trade("BTC/USDT", "sell", 0.1, 51000.0, "paper-2")
        trades = store.list_trades()
        assert len(trades) == 2
        assert trades[0]["side"] == "buy"
        assert trades[1]["side"] == "sell"

    def test_empty_list(self, tmp_path):
        db_path = tmp_path / "trades.sqlite3"
        store = TradeStore(db_path)
        assert store.list_trades() == []

    def test_init_db_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "subdir" / "deep" / "trades.sqlite3"
        store = TradeStore(db_path)
        assert db_path.exists()
