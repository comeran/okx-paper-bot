"""Tests for okx_paper_bot.store module."""
import tempfile
from pathlib import Path
from okx_paper_bot.store import TradeStore


class TestTradeStore:
    def test_record_and_list(self, tmp_path):
        db = tmp_path / "trades.sqlite3"
        store = TradeStore(db)
        store.record_trade("BTC/USDT", "buy", 0.01, 50000.0, "order-1")
        store.record_trade("BTC/USDT", "sell", 0.01, 51000.0, "order-2")
        trades = store.list_trades()
        assert len(trades) == 2
        assert trades[0]["symbol"] == "BTC/USDT"
        assert trades[0]["side"] == "buy"
        assert trades[0]["amount"] == 0.01
        assert trades[0]["price"] == 50000.0
        assert trades[0]["order_id"] == "order-1"
        assert trades[1]["side"] == "sell"

    def test_creates_parent_dirs(self, tmp_path):
        db = tmp_path / "sub" / "dir" / "trades.sqlite3"
        store = TradeStore(db)
        assert db.parent.exists()

    def test_empty_store(self, tmp_path):
        db = tmp_path / "empty.sqlite3"
        store = TradeStore(db)
        assert store.list_trades() == []
