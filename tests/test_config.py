"""Tests for okx_paper_bot.config module."""
import pytest
from okx_paper_bot.config import BotConfig, _parse_bool


class TestParseBool:
    def test_true_values(self):
        for v in ["1", "true", "True", "yes", "y", "on", "ON"]:
            assert _parse_bool(v) is True
    def test_false_values(self):
        for v in ["0", "false", "no", "n", "off", "anything"]:
            assert _parse_bool(v) is False
    def test_none_returns_default(self):
        assert _parse_bool(None) is False
        assert _parse_bool(None, default=True) is True


class TestBotConfig:
    def test_defaults(self):
        cfg = BotConfig()
        assert cfg.symbol == "BTC/USDT"
        assert cfg.stop_loss_pct == 0.05
        assert cfg.take_profit_pct == 0.10
        assert cfg.trailing_stop_pct == 0.0
        assert cfg.loop_interval_seconds == 60
    def test_frozen(self):
        cfg = BotConfig()
        with pytest.raises(AttributeError):
            cfg.symbol = "ETH/USDT"
    def test_from_env_custom(self, monkeypatch):
        monkeypatch.setenv("OKX_SYMBOL", "SOL/USDT")
        monkeypatch.setenv("STOP_LOSS_PCT", "0.03")
        cfg = BotConfig.from_env()
        assert cfg.symbol == "SOL/USDT"
        assert cfg.stop_loss_pct == 0.03
    def test_from_env_demo_flag(self, monkeypatch):
        monkeypatch.setenv("OKX_DEMO", "false")
        cfg = BotConfig.from_env()
        assert cfg.okx_demo is False
