"""Tests for okx_paper_bot.config module."""
import pytest
from okx_paper_bot.config import BotConfig, _parse_bool


class TestParseBool:
    def test_true_values(self):
        for v in ["1", "true", "True", "TRUE", "yes", "Yes", "y", "Y", "on", "ON"]:
            assert _parse_bool(v) is True

    def test_false_values(self):
        for v in ["0", "false", "no", "n", "off", "anything"]:
            assert _parse_bool(v) is False

    def test_none_returns_default(self):
        assert _parse_bool(None) is False
        assert _parse_bool(None, default=True) is True

    def test_whitespace_stripped(self):
        assert _parse_bool("  true  ") is True
        assert _parse_bool("  false  ") is False


class TestBotConfig:
    def test_defaults(self):
        cfg = BotConfig()
        assert cfg.symbol == "BTC/USDT"
        assert cfg.timeframe == "1m"
        assert cfg.okx_demo is True
        assert cfg.fast_window == 5
        assert cfg.slow_window == 20
        assert cfg.initial_balance_usdt == 1000.0
        assert cfg.order_usdt == 100.0
        assert cfg.max_position_fraction == 0.25

    def test_frozen(self):
        cfg = BotConfig()
        with pytest.raises(AttributeError):
            cfg.symbol = "ETH/USDT"

    def test_from_env_uses_defaults(self, monkeypatch):
        for key in ["OKX_SYMBOL", "OKX_TIMEFRAME", "OKX_DEMO", "FAST_WINDOW",
                     "SLOW_WINDOW", "INITIAL_BALANCE_USDT", "ORDER_USDT",
                     "MAX_POSITION_FRACTION", "DB_PATH", "OKX_API_KEY",
                     "OKX_API_SECRET", "OKX_API_PASSWORD"]:
            monkeypatch.delenv(key, raising=False)
        cfg = BotConfig.from_env()
        assert cfg.symbol == "BTC/USDT"
        assert cfg.api_key is None

    def test_from_env_custom(self, monkeypatch):
        monkeypatch.setenv("OKX_SYMBOL", "ETH/USDT")
        monkeypatch.setenv("FAST_WINDOW", "10")
        monkeypatch.setenv("SLOW_WINDOW", "30")
        monkeypatch.setenv("INITIAL_BALANCE_USDT", "5000")
        cfg = BotConfig.from_env()
        assert cfg.symbol == "ETH/USDT"
        assert cfg.fast_window == 10
        assert cfg.slow_window == 30
        assert cfg.initial_balance_usdt == 5000.0

    def test_from_env_demo_flag(self, monkeypatch):
        monkeypatch.setenv("OKX_DEMO", "false")
        cfg = BotConfig.from_env()
        assert cfg.okx_demo is False
