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
def config(db_path, tmp_dir):
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


# ── Task 6: POST /api/backtest (data handling) ───────────────────────────

class TestApiBacktest:

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

    def test_homepage_still_works(self, server_url):
        import urllib.request
        resp = urllib.request.urlopen(server_url)
        html = resp.read().decode()
        assert "OKX Paper Bot" in html
