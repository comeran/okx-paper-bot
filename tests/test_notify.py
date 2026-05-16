"""Tests for okx_paper_bot.notify module."""
import pytest
from okx_paper_bot.notify import format_trade_signal, format_error, format_status, notify


class TestFormatTradeSignal:
    def test_buy_signal(self):
        msg = format_trade_signal("BTC/USDT", "buy", 50000.0, 0.1, "closed", 9500.0, {"BTC/USDT": 0.1})
        assert "BUY" in msg and "50000.00" in msg
    def test_stop_loss_signal(self):
        msg = format_trade_signal("BTC/USDT", "stop_loss", 45000.0, 0.1, "closed", 10000.0, {}, reason="止损")
        assert "STOP_LOSS" in msg and "止损" in msg


class TestFormatError:
    def test_error_message(self):
        assert "ERROR" in format_error("BTC/USDT", "timeout")


class TestFormatStatus:
    def test_with_positions(self):
        msg = format_status("BTC/USDT", 50000.0, 5000.0, {"BTC/USDT": 0.1}, "hold")
        assert "50000.00" in msg
    def test_empty_positions(self):
        assert "空仓" in format_status("BTC/USDT", 50000.0, 10000.0, {}, "buy")


class TestNotify:
    def test_writes_to_file(self, tmp_path):
        nf = tmp_path / "test.log"
        notify("test msg", nf)
        assert nf.exists() and "test msg" in nf.read_text()
    def test_no_file_when_none(self):
        notify("test msg", None)
    def test_creates_parent_dirs(self, tmp_path):
        nf = tmp_path / "sub" / "dir" / "notify.log"
        notify("deep msg", nf)
        assert nf.exists()
