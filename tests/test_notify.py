"""Tests for okx_paper_bot.notify module."""
import pytest
from pathlib import Path
from okx_paper_bot.notify import (
    format_trade_signal,
    format_error,
    format_status,
    notify,
    _now_bjt,
)


class TestFormatTradeSignal:
    def test_buy_signal(self):
        msg = format_trade_signal("BTC/USDT", "buy", 50000.0, 0.1, "closed", 9500.0, {"BTC/USDT": 0.1})
        assert "BUY" in msg
        assert "BTC/USDT" in msg
        assert "50000.00" in msg
        assert "0.10000000" in msg
        assert "closed" in msg

    def test_stop_loss_signal(self):
        msg = format_trade_signal("BTC/USDT", "stop_loss", 45000.0, 0.1, "closed", 10000.0, {},
                                  reason="止损触发")
        assert "STOP_LOSS" in msg
        assert "止损触发" in msg

    def test_take_profit_signal(self):
        msg = format_trade_signal("BTC/USDT", "take_profit", 60000.0, 0.1, "closed", 11000.0, {})
        assert "TAKE_PROFIT" in msg


class TestFormatError:
    def test_error_message(self):
        msg = format_error("BTC/USDT", "connection timeout")
        assert "ERROR" in msg
        assert "connection timeout" in msg


class TestFormatStatus:
    def test_with_positions(self):
        msg = format_status("BTC/USDT", 50000.0, 5000.0, {"BTC/USDT": 0.1}, "hold")
        assert "50000.00" in msg
        assert "hold" in msg.lower()

    def test_empty_positions(self):
        msg = format_status("BTC/USDT", 50000.0, 10000.0, {}, "buy")
        assert "空仓" in msg


class TestNotify:
    def test_writes_to_file(self, tmp_path):
        nf = tmp_path / "test.log"
        notify("test message", nf)
        assert nf.exists()
        content = nf.read_text()
        assert "test message" in content

    def test_no_file_when_none(self, tmp_path):
        notify("test message", None)

    def test_creates_parent_dirs(self, tmp_path):
        nf = tmp_path / "sub" / "dir" / "notify.log"
        notify("deep msg", nf)
        assert nf.exists()
