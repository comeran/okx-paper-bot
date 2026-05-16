"""Tests for config."""
import pytest
from okx_paper_bot.config import BotConfig, _parse_bool

class TestParseBool:
    def test_true(self): assert _parse_bool("true") is True
    def test_false(self): assert _parse_bool("false") is False
    def test_none(self): assert _parse_bool(None) is False

class TestBotConfig:
    def test_defaults(self):
        c = BotConfig()
        assert c.symbol == "BTC/USDT" and c.strategy_name == "ma_crossover"
        assert c.fee_pct == 0.001 and c.rsi_period == 14
    def test_frozen(self):
        with pytest.raises(AttributeError): BotConfig().symbol = "X"
    def test_all_symbols(self):
        assert BotConfig().all_symbols == ["BTC/USDT"]
        assert BotConfig(symbols=("BTC/USDT","ETH/USDT")).all_symbols == ["BTC/USDT","ETH/USDT"]
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OKX_SYMBOL", "SOL/USDT"); monkeypatch.setenv("STRATEGY", "rsi")
        c = BotConfig.from_env(); assert c.symbol == "SOL/USDT" and c.strategy_name == "rsi"
