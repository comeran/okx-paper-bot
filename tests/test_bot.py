"""Tests for real-time TradingBot behavior."""
from __future__ import annotations

import pytest

from okx_paper_bot.bot import TradingBot
from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore


def test_paper_account_persists_initial_balance(tmp_path):
    from okx_paper_bot.paper import account_initial_balance, account_initial_mismatch

    account = PaperAccount(balance_usdt=800, initial_balance_usdt=1000)
    path = tmp_path / "account.json"
    account.save(path)

    loaded = PaperAccount.load(path, fallback_balance=500)

    assert loaded.balance_usdt == pytest.approx(800)
    assert account_initial_balance(loaded) == pytest.approx(1000)
    assert account_initial_mismatch(loaded, 900)


def test_realtime_bot_supports_macd(tmp_path):
    config = BotConfig(strategy_name="macd", fast_window=12, slow_window=26, db_path=tmp_path / "trades.sqlite3")
    bot = TradingBot(config, PaperAccount(balance_usdt=1000), TradeStore(config.db_path))

    result = bot.on_prices([100.0 + i * 0.2 for i in range(50)])

    assert result["signal"] in {"buy", "sell", "hold"}


def test_pyramiding_disabled_ignores_second_buy(tmp_path):
    config = BotConfig(
        strategy_name="rsi",
        rsi_period=14,
        rsi_buy=70.0,
        stop_loss_pct=0.99,
        take_profit_pct=10.0,
        allow_pyramiding=False,
        db_path=tmp_path / "trades.sqlite3",
    )
    account = PaperAccount(balance_usdt=1000)
    first = account.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
    assert first["status"] == "closed"
    bot = TradingBot(config, account, TradeStore(config.db_path))

    result = bot.on_prices([100.0 - i for i in range(20)], symbol="BTC/USDT")

    assert result["signal"] == "hold"
    assert result["reason"] == "pyramiding_disabled"
    assert account.total_held("BTC/USDT") == pytest.approx(1.0)


def test_pyramiding_enabled_adds_to_position_and_updates_average_entry(tmp_path):
    config = BotConfig(
        strategy_name="rsi",
        rsi_period=14,
        rsi_buy=70.0,
        stop_loss_pct=0.99,
        take_profit_pct=10.0,
        allow_pyramiding=True,
        order_usdt=100.0,
        db_path=tmp_path / "trades.sqlite3",
    )
    account = PaperAccount(balance_usdt=1000)
    account.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
    bot = TradingBot(config, account, TradeStore(config.db_path))

    result = bot.on_prices([100.0 - i for i in range(20)], symbol="BTC/USDT")

    assert result["signal"] == "buy"
    assert result["order"]["status"] == "closed"
    assert account.total_held("BTC/USDT") > 1.0
    assert bot._entry_prices["BTC/USDT"] == pytest.approx(account.avg_entry_price("BTC/USDT"))
