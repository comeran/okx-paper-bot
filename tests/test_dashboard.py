"""Tests for dashboard API endpoints."""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from urllib.parse import urlencode

import pytest

from okx_paper_bot.config import BotConfig
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.store import TradeStore
from okx_paper_bot.stats import EquitySnapshot, EquityTracker

BJT = timezone(timedelta(hours=8))

# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path

@pytest.fixture
def db_path(tmp_dir):
    return tmp_dir / "trades.sqlite3"

@pytest.fixture
def equity_path(tmp_dir):
    return tmp_dir / "equity_history.json"

@pytest.fixture
def store(db_path):
    return TradeStore(db_path)

@pytest.fixture
def config(db_path, tmp_dir, monkeypatch):
    monkeypatch.chdir(tmp_dir)
    return BotConfig(
        symbol="BTC/USDT",
        symbols=("BTC/USDT",),
        timeframe="1m",
        strategy_name="ma_crossover",
        fast_window=5,
        slow_window=20,
        initial_balance_usdt=1000.0,
        order_usdt=100.0,
        db_path=db_path,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

def _populate_trades(store: TradeStore, trades: list[dict]):
    """Insert pre-built trade dicts into the store."""
    for t in trades:
        store.record_trade(t["symbol"], t["side"], t["amount"], t["price"], t.get("order_id", "test-001"))


class TestStrategyInstanceValidation:

    def test_equity_is_required_only_for_enabled_instances(self):
        from okx_paper_bot.config import StrategyInstance, validate_strategy_instances

        errors = validate_strategy_instances([
            StrategyInstance(name="draft", enabled=False, symbols=["BTC/USDT"], equity=0.0),
            StrategyInstance(name="live", enabled=True, symbols=["ETH/USDT"], equity=0.0),
        ])

        assert not any("draft" in item and "分配权益" in item for item in errors)
        assert any("live" in item and "分配权益" in item for item in errors)

    def test_enabled_allocation_cannot_exceed_initial_balance(self):
        from okx_paper_bot.config import StrategyInstance, validate_strategy_allocation

        errors = validate_strategy_allocation([
            StrategyInstance(name="A", enabled=True, symbols=["BTC/USDT"], equity=700.0),
            StrategyInstance(name="B", enabled=True, symbols=["ETH/USDT"], equity=400.0),
            StrategyInstance(name="draft", enabled=False, symbols=["SOL/USDT"], equity=5000.0),
        ], initial_balance=1000.0)

        assert any("1100.00 USDT" in item and "1000.00 USDT" in item for item in errors)


# ── Task 1: /api/status ──────────────────────────────────────────────────

class TestApiStatus:

    def test_empty_trades(self, config):
        from okx_paper_bot.dashboard import _build_api_status
        result = _build_api_status(config)
        assert result["balance"] == 1000.0
        assert result["positions_value"] == 0.0
        assert result["total_equity"] == 1000.0
        assert result["return_pct"] == 0.0
        assert result["initial_balance"] == 1000.0
        assert result["strategy"] == "ma_crossover"
        assert result["positions"] == []
        assert result["trades_count"] == 0
        assert "time" in result

    def test_with_buy_trade(self, config, store):
        from okx_paper_bot.dashboard import _build_api_status
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        result = _build_api_status(config)
        assert result["trades_count"] == 1
        assert result["balance"] == pytest.approx(940.0)
        assert result["positions_value"] == pytest.approx(60.0)
        assert result["total_equity"] == pytest.approx(1000.0)
        assert len(result["positions"]) == 1
        assert result["positions"][0]["symbol"] == "BTC/USDT"

    def test_buy_and_sell(self, config, store):
        from okx_paper_bot.dashboard import _build_api_status
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "sell", 0.001, 62000.0, "ord-2")
        result = _build_api_status(config)
        assert result["trades_count"] == 2
        assert result["balance"] == pytest.approx(1002.0)
        assert result["positions_value"] == pytest.approx(0.0)
        assert result["total_equity"] == pytest.approx(1002.0)
        assert result["positions"] == []

    def test_stop_loss_exit(self, config, store):
        from okx_paper_bot.dashboard import _build_api_status
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "stop_loss", 0.001, 58000.0, "ord-2")
        result = _build_api_status(config)
        assert result["trades_count"] == 2
        assert result["positions"] == []


# ── Task 2: /api/trades ──────────────────────────────────────────────────

class TestApiTrades:

    def test_empty(self, config):
        from okx_paper_bot.dashboard import _build_api_trades
        result = _build_api_trades(config)
        assert result["trades"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["pages"] == 0

    def test_basic_listing(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades
        for i in range(5):
            store.record_trade("BTC/USDT", "buy", 0.001, 60000.0 + i, f"ord-{i}")
        result = _build_api_trades(config)
        assert result["total"] == 5
        assert len(result["trades"]) == 5
        assert result["page"] == 1
        assert result["pages"] == 1

    def test_filter_by_symbol(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("ETH/USDT", "buy", 0.01, 3000.0, "ord-2")
        result = _build_api_trades(config, symbol="BTC/USDT")
        assert result["total"] == 1
        assert result["trades"][0]["symbol"] == "BTC/USDT"

    def test_filter_by_side(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "sell", 0.001, 62000.0, "ord-2")
        result = _build_api_trades(config, side="buy")
        assert result["total"] == 1
        assert result["trades"][0]["side"] == "buy"

    def test_pagination(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades
        for i in range(25):
            store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, f"ord-{i}")
        result = _build_api_trades(config, page=2, per_page=10)
        assert result["total"] == 25
        assert len(result["trades"]) == 10
        assert result["page"] == 2
        assert result["pages"] == 3

    def test_last_page_partial(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades
        for i in range(25):
            store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, f"ord-{i}")
        result = _build_api_trades(config, page=3, per_page=10)
        assert len(result["trades"]) == 5


# ── Task 3: /api/equity ──────────────────────────────────────────────────

class TestApiEquity:

    def test_missing_file(self, tmp_dir):
        from okx_paper_bot.dashboard import _build_api_equity
        result = _build_api_equity(tmp_dir / "nonexistent.json")
        assert result["history"] == []
        assert result["sharpe"] == 0.0
        assert result["max_drawdown"] == 0.0

    def test_with_data(self, equity_path):
        from okx_paper_bot.dashboard import _build_api_equity
        # Write some equity snapshots
        data = [
            {"timestamp": "2024-01-01 00:00:00", "balance_usdt": 1000, "positions_value": 0, "total_equity": 1000, "pnl": 0, "pnl_pct": 0},
            {"timestamp": "2024-01-02 00:00:00", "balance_usdt": 1050, "positions_value": 0, "total_equity": 1050, "pnl": 50, "pnl_pct": 0.05},
            {"timestamp": "2024-01-03 00:00:00", "balance_usdt": 1020, "positions_value": 0, "total_equity": 1020, "pnl": 20, "pnl_pct": 0.02},
        ]
        equity_path.write_text(json.dumps(data))
        result = _build_api_equity(equity_path)
        assert len(result["history"]) == 3
        assert result["sharpe"] != 0.0  # non-zero with variance
        assert result["max_drawdown"] > 0.0  # drop from 1050 to 1020

    def test_single_snapshot(self, equity_path):
        from okx_paper_bot.dashboard import _build_api_equity
        data = [
            {"timestamp": "2024-01-01 00:00:00", "balance_usdt": 1000, "positions_value": 0, "total_equity": 1000, "pnl": 0, "pnl_pct": 0},
        ]
        equity_path.write_text(json.dumps(data))
        result = _build_api_equity(equity_path)
        assert len(result["history"]) == 1
        assert result["sharpe"] == 0.0
        assert result["max_drawdown"] == 0.0


# ── Task 4: /api/stats ──────────────────────────────────────────────────

class TestApiStats:

    def test_no_trades(self, config):
        from okx_paper_bot.dashboard import _build_api_stats
        result = _build_api_stats(config)
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0.0
        assert result["profit_factor"] == 0.0
        assert result["avg_win"] == 0.0
        assert result["avg_loss"] == 0.0

    def test_with_paired_trades(self, config, store):
        from okx_paper_bot.dashboard import _build_api_stats
        # Buy at 60000, sell at 62000 => profit 2000 * 0.001 = 2.0
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "sell", 0.001, 62000.0, "ord-2")
        result = _build_api_stats(config)
        assert result["total_trades"] == 1
        assert result["win_rate"] == 1.0
        assert result["avg_win"] == pytest.approx(2.0)
        assert result["avg_loss"] == 0.0

    def test_loss_trade(self, config, store):
        from okx_paper_bot.dashboard import _build_api_stats
        # Buy at 60000, sell at 58000 => loss -2000 * 0.001 = -2.0
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "sell", 0.001, 58000.0, "ord-2")
        result = _build_api_stats(config)
        assert result["total_trades"] == 1
        assert result["win_rate"] == 0.0
        assert result["avg_loss"] == pytest.approx(-2.0)

    def test_mixed_trades(self, config, store):
        from okx_paper_bot.dashboard import _build_api_stats
        # Trade 1: buy 60000, sell 62000 => +2.0
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "sell", 0.001, 62000.0, "ord-2")
        # Trade 2: buy 62000, sell 61000 => -1.0
        store.record_trade("BTC/USDT", "buy", 0.001, 62000.0, "ord-3")
        store.record_trade("BTC/USDT", "sell", 0.001, 61000.0, "ord-4")
        result = _build_api_stats(config)
        assert result["total_trades"] == 2
        assert result["win_rate"] == pytest.approx(0.5)
        assert result["profit_factor"] == pytest.approx(2.0)

    def test_stop_loss_trades(self, config, store):
        from okx_paper_bot.dashboard import _build_api_stats
        store.record_trade("BTC/USDT", "buy", 0.001, 60000.0, "ord-1")
        store.record_trade("BTC/USDT", "stop_loss", 0.001, 58000.0, "ord-2")
        result = _build_api_stats(config)
        assert result["total_trades"] == 1
        assert result["win_rate"] == 0.0
        assert result["avg_loss"] == pytest.approx(-2.0)


# ── Task 5: /api/config ──────────────────────────────────────────────────

class TestApiConfig:

    def test_no_sensitive_fields(self, config):
        from okx_paper_bot.dashboard import _build_api_config
        result = _build_api_config(config)
        assert "api_key" not in result
        assert "secret" not in result
        assert "password" not in result
        assert result["okx_api_key"] == ""

    def test_has_expected_fields(self, config):
        from okx_paper_bot.dashboard import _build_api_config
        result = _build_api_config(config)
        assert result["strategy"] == "ma_crossover"
        assert result["symbols"] == ["BTC/USDT"]
        assert result["timeframe"] == "1m"
        assert result["initial_balance"] == 1000.0
        assert result["fast_window"] == 5
        assert result["slow_window"] == 20
        assert result["stop_loss_pct"] == 0.05
        assert result["take_profit_pct"] == 0.10
        assert result["order_usdt"] == 100.0
        assert result["demo"] is True

    def test_rsi_params(self, config):
        from okx_paper_bot.dashboard import _build_api_config
        result = _build_api_config(config)
        assert "rsi_period" in result
        assert "rsi_buy" in result
        assert "rsi_sell" in result

    def test_bollinger_params(self, config):
        from okx_paper_bot.dashboard import _build_api_config
        result = _build_api_config(config)
        assert "bollinger_period" in result
        assert "bollinger_std" in result

    def test_update_api_config_writes_env(self, tmp_dir, monkeypatch):
        from okx_paper_bot import dashboard
        env_file = tmp_dir / ".env"
        env_file.write_text("OKX_API_KEY=keep-secret\nOKX_SYMBOL=BTC/USDT\n")
        monkeypatch.setenv("OKX_BOT_ENV_FILE", str(env_file))
        result = dashboard._update_api_config({
            "symbols": "BTC/USDT,ETH/USDT",
            "symbol": "ETH/USDT",
            "strategy": "rsi",
            "timeframe": "5m",
            "fast_window": 8,
            "slow_window": 21,
            "initial_balance": 2000.0,
            "order_usdt": 150.0,
            "max_position_fraction": 0.3,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.12,
            "trailing_stop_pct": 0.02,
            "loop_interval_seconds": 30,
        })
        content = env_file.read_text()
        assert "OKX_API_KEY=keep-secret" in content
        assert "OKX_SYMBOLS=BTC/USDT,ETH/USDT" in content
        assert "OKX_SYMBOL=ETH/USDT" in content
        assert "STRATEGY=rsi" in content
        assert "OKX_TIMEFRAME=5m" in content
        assert result["symbols"] == ["BTC/USDT", "ETH/USDT"]
        assert result["strategy"] == "rsi"
        assert result["fast_window"] == 8
        assert result["loop_interval_seconds"] == 30


# ── Task 6: POST /api/backtest (data handling) ───────────────────────────

class TestApiBacktest:

    def test_dashboard_backtest_imports_current_exchange_factory(self):
        from okx_paper_bot.exchange import create_okx_exchange
        assert callable(create_okx_exchange)

    def test_backtest_result_serialization(self):
        """Test that BacktestResult can be serialized to expected format."""
        from okx_paper_bot.backtest import BacktestResult, BacktestTrade
        result = BacktestResult(
            symbol="BTC/USDT",
            timeframe="1h",
            start_time="2024-01-01 00:00",
            end_time="2024-01-31 00:00",
            initial_balance=1000.0,
            final_balance=1050.0,
            trades=[
                BacktestTrade(
                    entry_time="2024-01-01 00:00",
                    entry_price=60000.0,
                    exit_time="2024-01-02 00:00",
                    exit_price=62000.0,
                    amount=0.001,
                    side="buy",
                    pnl=2.0,
                    pnl_pct=0.033,
                    exit_reason="signal",
                )
            ],
        )
        # Verify we can compute expected fields
        assert result.total_return == pytest.approx(0.05)
        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.win_rate == 1.0

    def test_build_backtest_result_json(self):
        """Test _build_backtest_result_json converts BacktestResult correctly."""
        from okx_paper_bot.backtest import BacktestResult, BacktestTrade
        from okx_paper_bot.dashboard import _build_backtest_result_json
        result = BacktestResult(
            symbol="BTC/USDT",
            timeframe="1h",
            start_time="2024-01-01 00:00",
            end_time="2024-01-31 00:00",
            initial_balance=1000.0,
            final_balance=1050.0,
            trades=[
                BacktestTrade(
                    entry_time="2024-01-01 00:00",
                    entry_price=60000.0,
                    exit_time="2024-01-02 00:00",
                    exit_price=62000.0,
                    amount=0.001,
                    side="buy",
                    pnl=2.0,
                    pnl_pct=0.033,
                    exit_reason="signal",
                ),
                BacktestTrade(
                    entry_time="2024-01-03 00:00",
                    entry_price=62000.0,
                    exit_time="2024-01-04 00:00",
                    exit_price=61000.0,
                    amount=0.001,
                    side="buy",
                    pnl=-1.0,
                    pnl_pct=-0.016,
                    exit_reason="signal",
                ),
            ],
        )
        data = _build_backtest_result_json(result)
        assert data["symbol"] == "BTC/USDT"
        assert data["total_return"] == pytest.approx(0.05)
        assert data["total_trades"] == 2
        assert data["winning_trades"] == 1
        assert data["win_rate"] == pytest.approx(0.5)
        assert len(data["trades"]) == 2
        assert data["trades"][0]["pnl"] == 2.0
        # Check cumulative equity
        assert len(data["equity_curve"]) == 3
        assert data["equity_curve"][0] == 1000.0
        assert data["equity_curve"][1] == pytest.approx(1002.0)
        assert data["equity_curve"][2] == pytest.approx(1001.0)


class TestApiGrid:

    def test_missing_grid_state_returns_disabled_demo(self, config, monkeypatch, tmp_dir):
        from okx_paper_bot.dashboard import _build_api_grid
        monkeypatch.setenv("GRID_STATE_FILE", str(tmp_dir / "missing_grid_state.json"))
        result = _build_api_grid(config)
        assert result["enabled"] is False
        assert result["symbol"] == "BTC/USDT"
        assert result["grid_count"] == 10
        assert result["grid_step"] == 2000.0
        assert len(result["levels"]) == 11
        assert result["bought_pending"] == 0
        assert result["available"] == 11

    def test_grid_state_file(self, config, monkeypatch, tmp_dir):
        from okx_paper_bot.dashboard import _build_api_grid
        grid_file = tmp_dir / "grid_state.json"
        grid_file.write_text(json.dumps({
            "config": {"symbol": "ETH/USDT", "lower_price": 2000, "upper_price": 3000, "grid_count": 5, "order_usdt": 100},
            "levels": [
                {"price": 2000, "buy_filled": False, "sell_filled": False},
                {"price": 2200, "buy_filled": True, "sell_filled": False},
                {"price": 2400, "buy_filled": True, "sell_filled": True},
            ],
            "total_profit": 12.34,
            "completed_grids": 1,
        }))
        monkeypatch.setenv("GRID_STATE_FILE", str(grid_file))
        result = _build_api_grid(config)
        assert result["enabled"] is True
        assert result["symbol"] == "ETH/USDT"
        assert result["grid_step"] == 200.0
        assert result["total_profit"] == pytest.approx(12.34)
        assert result["completed_grids"] == 1
        assert result["bought_pending"] == 1
        assert result["available"] == 1


class TestApiControl:

    def test_invalid_action(self):
        from okx_paper_bot.dashboard import _build_api_control
        result = _build_api_control("boom")
        assert "error" in result

    def test_control_uses_systemctl_when_available(self, monkeypatch):
        from okx_paper_bot import dashboard
        monkeypatch.setattr(dashboard, "_systemctl_bot", lambda action: True)
        monkeypatch.setattr(dashboard, "_find_bot_pids", lambda: [])
        result = dashboard._build_api_control("restart")
        assert result == {"status": "ok", "action": "restart", "method": "systemctl"}

    def test_control_fallback_sends_sigterm(self, monkeypatch):
        from okx_paper_bot import dashboard
        killed = []
        monkeypatch.setattr(dashboard, "_systemctl_bot", lambda action: False)
        monkeypatch.setattr(dashboard, "_find_bot_pids", lambda: [123, 456])
        monkeypatch.setattr(dashboard.os, "kill", lambda pid, sig: killed.append((pid, sig)))
        result = dashboard._build_api_control("stop")
        assert result["status"] == "ok"
        assert result["method"] == "sigterm"
        assert [pid for pid, _sig in killed] == [123, 456]

    def test_reset_single_strategy_deletes_only_instance_rows(self, tmp_dir):
        from okx_paper_bot.dashboard import _reset_strategy

        db = tmp_dir / "trades.sqlite3"
        config = BotConfig(db_path=db)
        store = TradeStore(db)
        store.record_trade("BTC/USDT", "buy", 1.0, 100.0, "a1", instance_name="A")
        store.record_trade("ETH/USDT", "buy", 1.0, 100.0, "b1", instance_name="B")

        result = _reset_strategy("A", config)

        assert result["status"] == "ok"
        rows = TradeStore(db).list_trades()
        assert [r["instance_name"] for r in rows] == ["B"]


# ── Dashboard v4 per-instance data layer ─────────────────────────────────

class TestDashboardV4:

    def test_trades_keep_instance_strategy_metadata_and_filter(self, config, store):
        from okx_paper_bot.dashboard import _build_api_trades

        store.record_trade("BTC/USDT", "buy", 1.0, 100.0, "a-buy", instance_name="A", strategy_name="ma_crossover")
        store.record_trade("BTC/USDT", "buy", 1.0, 200.0, "b-buy", instance_name="B", strategy_name="rsi")
        store.record_trade("BTC/USDT", "sell", 1.0, 110.0, "a-sell", instance_name="A", strategy_name="ma_crossover")

        result = _build_api_trades(config, instance="A")
        assert result["total"] == 2
        rows = list(reversed(result["trades"]))
        assert [r["instance_name"] for r in rows] == ["A", "A"]
        assert rows[1]["pnl"] == pytest.approx(10.0)

    def test_pnl_fifo_is_isolated_by_instance_for_same_symbol(self, config, store):
        from okx_paper_bot.dashboard import _build_api_stats

        store.record_trade("BTC/USDT", "buy", 1.0, 100.0, "a-buy", instance_name="A", strategy_name="ma_crossover")
        store.record_trade("BTC/USDT", "buy", 1.0, 200.0, "b-buy", instance_name="B", strategy_name="rsi")
        store.record_trade("BTC/USDT", "sell", 1.0, 110.0, "a-sell", instance_name="A", strategy_name="ma_crossover")
        store.record_trade("BTC/USDT", "sell", 1.0, 180.0, "b-sell", instance_name="B", strategy_name="rsi")

        a = _build_api_stats(config, instance="A")
        b = _build_api_stats(config, instance="B")
        assert a["total_pnl"] == pytest.approx(10.0)
        assert b["total_pnl"] == pytest.approx(-20.0)
        assert a["win_rate"] == pytest.approx(1.0)
        assert b["win_rate"] == pytest.approx(0.0)

    def test_dashboard_v4_payload_has_account_instances_and_strategy_compare(self, config, store):
        from okx_paper_bot.dashboard import _build_api_dashboard_v4

        store.record_trade("BTC/USDT", "buy", 1.0, 100.0, "a-buy", instance_name="A", strategy_name="ma_crossover")
        store.record_trade("BTC/USDT", "sell", 1.0, 110.0, "a-sell", instance_name="A", strategy_name="ma_crossover")
        store.record_trade("ETH/USDT", "buy", 2.0, 50.0, "b-buy", instance_name="B", strategy_name="rsi")
        store.record_trade("ETH/USDT", "sell", 2.0, 45.0, "b-sell", instance_name="B", strategy_name="rsi")

        payload = _build_api_dashboard_v4(config)
        assert payload["version"] == "v4"
        assert "account" in payload and "stats" in payload["account"]
        by_strategy = {s["strategy"]: s for s in payload["strategies"]}
        assert by_strategy["ma_crossover"]["total_pnl"] == pytest.approx(10.0)
        assert by_strategy["rsi"]["total_pnl"] == pytest.approx(-10.0)
        assert payload["totals"]["trades_count"] == 4

    def test_valid_instances_use_account_state_as_truth(self, tmp_dir, monkeypatch):
        from okx_paper_bot.config import StrategyInstance, save_strategy_instances
        from okx_paper_bot.dashboard import _build_api_dashboard_v4

        monkeypatch.chdir(tmp_dir)
        db = tmp_dir / "trades.sqlite3"
        config = BotConfig(db_path=db, initial_balance_usdt=9999.0)
        save_strategy_instances([
            StrategyInstance(name="A", enabled=True, strategy="ma_crossover", symbols=["BTC/USDT"], equity=1500.0)
        ], tmp_dir)
        account = PaperAccount(balance_usdt=1200.0, initial_balance_usdt=1500.0)
        account.execute_market_order("BTC/USDT", "buy", 1.0, 100.0)
        account.save(tmp_dir / "account_A.json")
        store = TradeStore(db)
        store.record_trade("BTC/USDT", "buy", 1.0, 200.0, "audit-row", instance_name="A", strategy_name="ma_crossover")

        payload = _build_api_dashboard_v4(config)
        inst = payload["instances"][0]
        assert inst["initial_balance"] == 1500.0
        assert inst["balance"] == pytest.approx(account.balance_usdt)
        assert inst["positions"][0]["amount"] == pytest.approx(1.0)
        # Price is the latest audited market price, but amount/balance come from PaperAccount.
        assert inst["positions"][0]["price"] == pytest.approx(200.0)

    def test_dashboard_overview_counts_only_enabled_allocations(self, tmp_dir, monkeypatch):
        from okx_paper_bot.config import StrategyInstance, save_strategy_instances
        from okx_paper_bot.dashboard import _build_api_dashboard_v4

        monkeypatch.chdir(tmp_dir)
        config = BotConfig(db_path=tmp_dir / "trades.sqlite3", initial_balance_usdt=2000.0)
        save_strategy_instances([
            StrategyInstance(name="A", enabled=True, symbols=["BTC/USDT"], equity=600.0),
            StrategyInstance(name="B", enabled=False, symbols=["ETH/USDT"], equity=1000.0),
        ], tmp_dir)
        PaperAccount(balance_usdt=600.0).save(tmp_dir / "account_A.json")

        payload = _build_api_dashboard_v4(config)

        assert payload["account"]["stats"]["initial_balance"] == pytest.approx(600.0)
        assert payload["account"]["stats"]["total_equity"] == pytest.approx(600.0)
        rows = {row["name"]: row for row in payload["instances"]}
        assert rows["A"]["account_state"] == "ok"
        assert rows["B"]["account_state"] == "disabled"

    def test_validation_blocks_zero_equity_and_missing_account_with_trades(self, tmp_dir, monkeypatch):
        from okx_paper_bot.config import StrategyInstance, save_strategy_instances
        from okx_paper_bot.dashboard import _build_api_validation

        monkeypatch.chdir(tmp_dir)
        db = tmp_dir / "trades.sqlite3"
        config = BotConfig(db_path=db)
        save_strategy_instances([
            StrategyInstance(name="A", enabled=True, symbols=["BTC/USDT"], equity=0.0),
            StrategyInstance(name="B", enabled=True, symbols=["ETH/USDT"], equity=1000.0),
        ], tmp_dir)
        TradeStore(db).record_trade("ETH/USDT", "buy", 1.0, 100.0, "b1", instance_name="B", strategy_name="rsi")

        result = _build_api_validation(config)
        assert result["status"] == "blocked"
        assert any("分配权益" in item for item in result["blockers"])
        assert any("账户状态文件不存在" in item for item in result["blockers"])

    def test_validation_blocks_account_initial_balance_mismatch(self, tmp_dir, monkeypatch):
        from okx_paper_bot.config import StrategyInstance, save_strategy_instances
        from okx_paper_bot.dashboard import _build_api_validation, _build_api_dashboard_v4

        monkeypatch.chdir(tmp_dir)
        config = BotConfig(db_path=tmp_dir / "trades.sqlite3")
        save_strategy_instances([
            StrategyInstance(name="A", enabled=True, symbols=["BTC/USDT"], equity=200.0),
        ], tmp_dir)
        PaperAccount(balance_usdt=20000.0).save(tmp_dir / "account_A.json")

        result = _build_api_validation(config)
        payload = _build_api_dashboard_v4(config)

        assert result["status"] == "blocked"
        assert any("账户初始资金" in item and "分配权益" in item for item in result["blockers"])
        assert payload["instances"][0]["account_state"] == "allocation_mismatch"

    def test_disabled_zero_equity_instance_does_not_display_global_balance(self, tmp_dir, monkeypatch):
        from okx_paper_bot.config import StrategyInstance, save_strategy_instances
        from okx_paper_bot.dashboard import _build_api_dashboard_v4

        monkeypatch.chdir(tmp_dir)
        config = BotConfig(db_path=tmp_dir / "trades.sqlite3", initial_balance_usdt=10000.0)
        save_strategy_instances([
            StrategyInstance(name="A", symbols=["BTC/USDT"], equity=0.0),
            StrategyInstance(name="B", symbols=["ETH/USDT"], equity=0.0),
        ], tmp_dir)

        payload = _build_api_dashboard_v4(config)

        assert payload["account"]["stats"]["total_equity"] == pytest.approx(10000.0)
        assert [row["total_equity"] for row in payload["instances"]] == [0.0, 0.0]
        assert all(row["account_state"] == "disabled" for row in payload["instances"])


class TestFastAPI:

    @pytest.fixture
    def client(self, tmp_dir, monkeypatch):
        from fastapi.testclient import TestClient
        from okx_paper_bot.dashboard import create_app

        monkeypatch.chdir(tmp_dir)
        monkeypatch.setenv("DB_PATH", str(tmp_dir / "trades.sqlite3"))
        monkeypatch.setenv("INITIAL_BALANCE_USDT", "1000")
        monkeypatch.setenv("STRATEGY", "ma_crossover")
        monkeypatch.setenv("OKX_TIMEFRAME", "1m")
        monkeypatch.setenv("OKX_API_KEY", "key")
        monkeypatch.setenv("OKX_API_SECRET", "secret")
        monkeypatch.setenv("OKX_API_PASSWORD", "pass")
        return TestClient(create_app())

    def test_health_and_config_do_not_leak_secrets(self, client):
        assert client.get("/api/health").json()["status"] == "ok"
        config = client.get("/api/config").json()
        assert config["strategy"] == "ma_crossover"
        assert config["okx_api_secret"] == "***"
        assert config["okx_api_key"] == "***"
        assert "secret" not in config
        assert "password" not in config

    def test_instances_save_allows_disabled_zero_equity_draft(self, client):
        response = client.post("/api/instances", json={"instances": [{
            "name": "bad", "strategy": "rsi", "symbols": ["BTC/USDT"], "equity": 0
        }]})
        assert response.status_code == 200
        validation = client.get("/api/validation").json()
        assert validation["status"] == "blocked"
        assert any("未启用任何策略" in item for item in validation["blockers"])
        assert not any("分配权益" in item for item in validation["blockers"])

    def test_instances_save_rejects_enabled_zero_equity(self, client):
        response = client.post("/api/instances", json={"instances": [{
            "name": "bad", "enabled": True, "strategy": "rsi", "symbols": ["BTC/USDT"], "equity": 0
        }]})
        assert response.status_code == 400
        assert any("分配权益" in item for item in response.json()["details"])

    def test_instances_save_rejects_enabled_allocation_over_initial_balance(self, client):
        response = client.post("/api/instances", json={"instances": [
            {"name": "A", "enabled": True, "strategy": "ma_crossover", "symbols": ["BTC/USDT"], "equity": 700},
            {"name": "B", "enabled": True, "strategy": "rsi", "symbols": ["ETH/USDT"], "equity": 400},
        ]})
        assert response.status_code == 400
        assert any("超过初始资金" in item for item in response.json()["details"])

    def test_instances_save_accepts_valid_payload(self, client):
        response = client.post("/api/instances", json={"instances": [{
            "name": "ok", "enabled": True, "strategy": "macd", "symbols": ["BTC/USDT"], "equity": 1000,
            "fast_window": 12, "slow_window": 26, "allow_pyramiding": True
        }]})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        rows = client.get("/api/instances").json()["instances"]
        assert rows[0]["enabled"] is True
        assert rows[0]["allow_pyramiding"] is True

    def test_dashboard_rows_can_be_saved_after_editing_equity(self, client):
        client.post("/api/instances", json={"instances": [
            {"name": "MA-BTC", "strategy": "ma_crossover", "symbols": ["BTC/USDT"], "equity": 1000},
            {"name": "RSI-ETH", "strategy": "rsi", "symbols": ["ETH/USDT"], "equity": 1000},
        ]})
        rows = client.get("/api/dashboard_v4").json()["instances"]
        assert all("equity" in row for row in rows)
        assert all("allow_pyramiding" in row for row in rows)
        rows[0]["equity"] = 1500

        response = client.post("/api/instances", json={"instances": rows})

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        saved = client.get("/api/instances").json()["instances"]
        assert saved[0]["equity"] == 1500

    def test_backtest_endpoint_uses_market_data_exchange(self, client, monkeypatch):
        import okx_paper_bot.exchange as exchange_module

        start_ms = int((datetime.now(timezone.utc) - timedelta(minutes=79)).timestamp() * 1000)
        candles = [
            [start_ms + i * 60_000, 100 + i, 101 + i, 99 + i, 100 + i, 10]
            for i in range(80)
        ]

        class FakeMarketExchange:
            def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
                rows = [c for c in candles if since is None or c[0] >= since]
                return rows[: limit or len(rows)]

        monkeypatch.setattr(exchange_module, "create_okx_market_data_exchange", lambda config: FakeMarketExchange())

        response = client.post("/api/backtest", json={
            "symbol": "BTC/USDT", "strategy": "ma_crossover", "timeframe": "1m", "days": 1
        })

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "BTC/USDT"
        assert data["strategy"] == "ma_crossover"
        assert data["candles"] == 80

    def test_backtest_endpoint_rejects_invalid_window(self, client):
        response = client.post("/api/backtest", json={
            "symbol": "BTC/USDT", "strategy": "ma_crossover", "fast": 20, "slow": 5
        })
        assert response.status_code == 400
        assert "fast" in response.json()["error"]

    def test_klines_endpoint_returns_clear_exchange_error(self, client, monkeypatch):
        import okx_paper_bot.exchange as exchange_module

        class BrokenMarketExchange:
            def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
                raise RuntimeError("exchange unavailable")

        monkeypatch.setattr(exchange_module, "create_okx_market_data_exchange", lambda config: BrokenMarketExchange())

        response = client.get("/api/klines?symbol=BTC/USDT&timeframe=1m&days=1")

        assert response.status_code == 502
        assert response.json()["error"] == "exchange unavailable"

    def test_process_status_works_without_proc(self, monkeypatch):
        from okx_paper_bot import dashboard

        real_path = dashboard.Path

        class NoProc:
            def exists(self): return False

        def fake_path(value):
            if value == "/proc":
                return NoProc()
            return real_path(value)

        monkeypatch.setattr(dashboard, "Path", fake_path)
        monkeypatch.setattr(dashboard, "_find_bot_pids", lambda: [])
        assert dashboard._build_api_bot_status()["running"] is False

    def test_bot_process_matcher_ignores_pgrep_commands(self):
        from okx_paper_bot.dashboard import _is_bot_run_cmd

        assert _is_bot_run_cmd("/venv/bin/python3 -m okx_paper_bot.cli run")
        assert _is_bot_run_cmd("/venv/bin/okx-paper-bot run")
        assert not _is_bot_run_cmd("pgrep -af okx_paper_bot.cli.* run")
        assert not _is_bot_run_cmd("uv run --group dev python - <<'PY' okx_paper_bot.cli.* run")


# ── HTTP integration tests ───────────────────────────────────────────────

class TestDashboardHTTP:
    """Integration tests using a real HTTP server."""

    @pytest.fixture
    def server_url(self, config, tmp_dir, monkeypatch):
        """Start a test dashboard server on a random port."""
        # Set env vars so from_env works
        monkeypatch.setenv("DB_PATH", str(config.db_path))
        monkeypatch.setenv("INITIAL_BALANCE_USDT", str(config.initial_balance_usdt))
        monkeypatch.setenv("STRATEGY", config.strategy_name)
        monkeypatch.setenv("OKX_SYMBOL", config.symbol)
        monkeypatch.setenv("OKX_TIMEFRAME", config.timeframe)
        monkeypatch.setenv("FAST_WINDOW", str(config.fast_window))
        monkeypatch.setenv("SLOW_WINDOW", str(config.slow_window))
        monkeypatch.setenv("STOP_LOSS_PCT", str(config.stop_loss_pct))
        monkeypatch.setenv("TAKE_PROFIT_PCT", str(config.take_profit_pct))
        monkeypatch.setenv("ORDER_USDT", str(config.order_usdt))
        monkeypatch.setenv("EQUITY_HISTORY_FILE", str(tmp_dir / "equity_history.json"))
        monkeypatch.setenv("GRID_STATE_FILE", str(tmp_dir / "grid_state.json"))

        from okx_paper_bot.dashboard import DashboardHandler, run_dashboard
        import socket

        # Find free port
        s = socket.socket()
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()

        server = HTTPServer(("127.0.0.1", port), DashboardHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        sleep(0.2)
        yield f"http://127.0.0.1:{port}"
        server.shutdown()

    def test_get_status(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/status")
        data = json.loads(resp.read())
        assert resp.status == 200
        assert "balance" in data
        assert "positions" in data
        assert "trades_count" in data

    def test_get_trades(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/trades")
        data = json.loads(resp.read())
        assert "trades" in data
        assert "total" in data
        assert "page" in data

    def test_get_equity(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/equity")
        data = json.loads(resp.read())
        assert "history" in data
        assert "sharpe" in data
        assert "max_drawdown" in data

    def test_get_stats(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/stats")
        data = json.loads(resp.read())
        assert "total_trades" in data
        assert "win_rate" in data

    def test_get_config(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/config")
        data = json.loads(resp.read())
        assert "api_key" not in data
        assert "strategy" in data

    def test_get_grid(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(f"{server_url}/api/grid")
        data = json.loads(resp.read())
        assert resp.status == 200
        assert "levels" in data
        assert "enabled" in data

    def test_homepage_still_works(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(server_url)
        html = resp.read().decode()
        assert "OKX Paper Bot" in html
