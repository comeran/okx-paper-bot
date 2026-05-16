"""Tests for okx_paper_bot.config module."""
import os
from unittest.mock import patch
from okx_paper_bot.config import BotConfig, _parse_bool


class TestBotConfig:
    def test_defaults(self):
        c = BotConfig()
        assert c.symbol == "BTC/USDT"
        assert c.timeframe == "1m"
        assert c.okx_demo is True
        assert c.fast_window == 5
        assert c.slow_window == 20
        assert c.initial_balance_usdt == 1000.0
        assert c.order_usdt == 100.0

    def test_from_env(self):
        env = {
            "OKX_SYMBOL": "ETH/USDT",
            "OKX_TIMEFRAME": "5m",
            "FAST_WINDOW": "10",
            "SLOW_WINDOW": "30",
        }
        with patch.dict(os.environ, env, clear=False):
            c = BotConfig.from_env()
        assert c.symbol == "ETH/USDT"
        assert c.timeframe == "5m"
        assert c.fast_window == 10
        assert c.slow_window == 30


class TestParseBool:
    def test_truthy_values(self):
        for v in ("1", "true", "True", "YES", "y", "on"):
            assert _parse_bool(v) is True

    def test_falsy_values(self):
        for v in ("0", "false", "no", "off", ""):
            assert _parse_bool(v) is False

    def test_none_returns_default(self):
        assert _parse_bool(None) is False
        assert _parse_bool(None, default=True) is True
