"""Tests for notify."""
from okx_paper_bot.notify import format_trade_signal, format_error, format_status, notify

class TestFormat:
    def test_buy(self): assert "BUY" in format_trade_signal("BTC/USDT", "buy", 50000.0, 0.1, "closed", 9500.0, {"BTC/USDT": 0.1})
    def test_sl(self): assert "STOP_LOSS" in format_trade_signal("BTC/USDT", "stop_loss", 45000.0, 0.1, "closed", 10000.0, {}, reason="止损")
    def test_error(self): assert "ERROR" in format_error("BTC/USDT", "timeout")
    def test_status(self): assert "50000.00" in format_status("BTC/USDT", 50000.0, 5000.0, {"BTC/USDT": 0.1}, "hold")
    def test_empty(self): assert "空仓" in format_status("BTC/USDT", 50000.0, 10000.0, {}, "buy")

class TestNotify:
    def test_file(self, tmp_path):
        nf = tmp_path / "test.log"; notify("hello", nf)
        assert nf.exists() and "hello" in nf.read_text()
    def test_dirs(self, tmp_path):
        nf = tmp_path / "a" / "b.log"; notify("x", nf)
        assert nf.exists()
