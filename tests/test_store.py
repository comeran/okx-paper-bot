"""Tests for store."""
from okx_paper_bot.store import TradeStore

class TestTradeStore:
    def test_init(self, tmp_path): assert TradeStore(tmp_path / "t.sqlite3").list_trades() == []
    def test_record(self, tmp_path):
        s = TradeStore(tmp_path / "t.sqlite3")
        s.record_trade("BTC/USDT", "buy", 0.1, 50000.0, "p-1")
        assert len(s.list_trades()) == 1
    def test_empty(self, tmp_path): assert TradeStore(tmp_path / "t.sqlite3").list_trades() == []
