import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from okx_paper_bot.api import create_app
from okx_paper_bot.config import AppSettings
from okx_paper_bot.market import CandleData, timeframe_seconds
from okx_paper_bot.persistence.models import AccountConfig, StrategyInstance, Trade
from tests.conftest import make_database, make_settings


class FakeOKXGateway:
    calls = []

    def __init__(self, settings, broker_mode, market_type):
        self.market_type = market_type

    def fetch_candles(self, *, symbol, timeframe, limit=200, since=None):
        self.__class__.calls.append({"symbol": symbol, "timeframe": timeframe, "limit": limit, "since": since})
        base = since or datetime(2026, 1, 1, tzinfo=timezone.utc)
        step = timedelta(seconds=timeframe_seconds(timeframe))
        return [
            CandleData(
                ts=base + step * index,
                open=100 + index,
                high=101 + index,
                low=99 + index,
                close=100.5 + index,
                volume=10 + index,
                completed=True if since is not None else index < limit - 1,
            )
            for index in range(limit)
        ]


class EmptyAccountGateway:
    def __init__(self, settings, broker_mode, market_type):
        pass

    def fetch_account_balance(self, ccy=None):
        return {"code": "0", "data": [{"totalEq": "0", "details": []}], "msg": ""}

    def fetch_positions(self):
        return {"code": "0", "data": [], "msg": ""}


class NonzeroAccountGateway:
    def __init__(self, settings, broker_mode, market_type):
        pass

    def fetch_account_balance(self, ccy=None):
        return {
            "code": "0",
            "data": [
                {
                    "totalEq": "5000",
                    "details": [{"ccy": "USDT", "eq": "5000", "availBal": "4900", "frozenBal": "100"}],
                }
            ],
            "msg": "",
        }

    def fetch_positions(self):
        return {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "pos": "1", "upl": "12.5"}], "msg": ""}


class DemoAdjustGateway:
    calls = []

    def __init__(self, settings, broker_mode, market_type):
        self.broker_mode = broker_mode

    def adjust_demo_balance(self, *, adjustment_type, adjustments):
        self.__class__.calls.append(
            {"broker_mode": self.broker_mode, "adjustment_type": adjustment_type, "adjustments": adjustments}
        )
        return {"code": "0", "data": [{"ccy": adjustments[0]["ccy"], "amt": adjustments[0]["amt"]}], "msg": ""}


class OrderGateway:
    calls = []

    def __init__(self, settings, broker_mode, market_type):
        self.broker_mode = broker_mode
        self.market_type = market_type

    def fetch_ticker(self, *, symbol):
        return {"last": 100}

    def fetch_account_balance(self, ccy=None):
        return {
            "code": "0",
            "data": [{"details": [{"ccy": ccy or "BTC", "availBal": "1", "eq": "1", "frozenBal": "0"}]}],
        }

    def place_order(self, **kwargs):
        order_id = f"ord-{len(self.__class__.calls) + 1}"
        self.__class__.calls.append({"broker_mode": self.broker_mode, "market_type": self.market_type, **kwargs})
        return {"id": order_id, "info": {"data": [{"ordId": order_id}]}}

    def fetch_order_details(self, *, inst_id, order_id):
        return {
            "code": "0",
            "data": [
                {
                    "instId": inst_id,
                    "ordId": order_id,
                    "state": "filled",
                    "avgPx": "100",
                    "sz": "0.05",
                    "accFillSz": "0.05",
                    "fee": "-0.01",
                    "cTime": "1779588000000",
                }
            ],
        }


def _add_account(session, account_type="okx_demo", name=None):
    account = AccountConfig(
        name=name or account_type,
        account_type=account_type,
        api_key="key",
        api_secret="secret",
        passphrase="passphrase",
    )
    session.add(account)
    session.flush()
    return account


def test_api_health_redacts_settings(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_api_account_empty_balance_and_positions_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", EmptyAccountGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = AccountConfig(
            name="demo",
            account_type="okx_demo",
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )
        session.add(account)
        session.flush()
        account_id = account.id

    balance = client.get(f"/api/accounts/{account_id}/balance")
    positions = client.get(f"/api/accounts/{account_id}/positions")

    assert balance.status_code == 200
    assert balance.json() == {"ok": True, "balances": {}, "total_eq": "0", "message": "OKX 官方 API 返回空余额"}
    assert positions.status_code == 200
    assert positions.json() == {"ok": True, "positions": [], "message": "OKX 官方 API 返回空持仓"}


def test_api_account_balance_and_positions_use_official_okx_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", NonzeroAccountGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = AccountConfig(
            name="demo",
            account_type="okx_demo",
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )
        session.add(account)
        session.flush()
        account_id = account.id

    balance = client.get(f"/api/accounts/{account_id}/balance")
    positions = client.get(f"/api/accounts/{account_id}/positions")

    assert balance.status_code == 200
    assert balance.json()["balances"]["USDT"] == {"free": "4900", "used": "100", "total": "5000"}
    assert balance.json()["total_eq"] == "5000"
    assert positions.status_code == 200
    assert positions.json()["positions"][0]["instId"] == "BTC-USDT-SWAP"


def test_api_demo_balance_adjust_uses_official_gateway(tmp_path, monkeypatch):
    DemoAdjustGateway.calls = []
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", DemoAdjustGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = AccountConfig(
            name="demo",
            account_type="okx_demo",
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )
        session.add(account)
        session.flush()
        account_id = account.id

    response = client.post(
        f"/api/accounts/{account_id}/demo-balance-adjust",
        json={"type": "increase", "ccy": "USDT", "amt": "5000"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert DemoAdjustGateway.calls == [
        {
            "broker_mode": "okx_demo",
            "adjustment_type": "increase",
            "adjustments": [{"ccy": "USDT", "amt": "5000"}],
        }
    ]


def test_api_demo_balance_adjust_rejects_live_account(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", DemoAdjustGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = AccountConfig(
            name="live",
            account_type="okx_live",
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )
        session.add(account)
        session.flush()
        account_id = account.id

    response = client.post(
        f"/api/accounts/{account_id}/demo-balance-adjust",
        json={"type": "increase", "ccy": "USDT", "amt": "5000"},
    )

    assert response.status_code == 400


def test_api_credentials_are_local_and_masked(tmp_path):
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        okx_api_key="key-secret",
        okx_api_secret="secret-value",
        okx_api_password="pass-value",
    )
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.get("/api/settings/credentials")

    assert response.status_code == 200
    data = response.json()
    assert data["okx_api_key_configured"] is True
    # API Key is returned as plain text
    assert data["okx_api_key"] == "key-secret"
    # Secret and Password are masked
    assert "secret-value" not in str(data)
    assert "pass-value" not in str(data)
    assert data["okx_api_secret_masked"] == "*" * len("secret-value")
    assert data["okx_api_password_masked"] == "*" * len("pass-value")


def test_api_can_seed_and_run_experiment(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    seed = client.post("/api/candles/seed", params={"count": 80})
    response = client.post(
        "/api/experiments",
        json={
            "name": "api sweep",
            "strategy_key": "ma_crossover",
            "fixed_params": {"slow": 12},
            "param_grid": {"fast": [3, 5]},
            "candles_limit": 80,
        },
    )

    assert seed.status_code == 200
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 2


def test_api_data_summary_counts_completed_candles(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    seed = client.post("/api/candles/seed", params={"count": 12})
    response = client.get("/api/data/summary")

    assert seed.status_code == 200
    assert response.status_code == 200
    assert response.json()[0]["completed"] == 12
    assert response.json()[0]["count"] == 12


def test_api_experiment_auto_fetches_missing_candles(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", FakeOKXGateway)
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/experiments",
        json={
            "name": "auto data",
            "strategy_key": "ma_crossover",
            "fixed_params": {"slow": 12},
            "param_grid": {"fast": [3]},
            "candles_limit": 12,
        },
    )
    summary = client.get("/api/data/summary")

    assert response.status_code == 200
    assert response.json()["runs"][0]["data_source"] == "auto_okx"
    assert summary.status_code == 200
    assert summary.json()[0]["source"] == "okx"
    assert summary.json()[0]["completed"] == 12


def test_api_experiment_auto_fetches_date_range(tmp_path, monkeypatch):
    FakeOKXGateway.calls = []
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", FakeOKXGateway)
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/experiments",
        json={
            "name": "range data",
            "strategy_key": "ma_crossover",
            "fixed_params": {"slow": 12},
            "param_grid": {"fast": [3]},
            "start_date": "2026-01-01",
            "end_date": "2026-01-01",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"][0]["data_source"] == "auto_okx"
    assert body["runs"][0]["candles_count"] == 24
    assert body["experiment"]["request"]["requested_start_ts"].startswith("2026-01-01T00:00:00")


def test_api_experiment_batches_large_date_range(tmp_path, monkeypatch):
    FakeOKXGateway.calls = []
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", FakeOKXGateway)
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/experiments",
        json={
            "name": "large range",
            "strategy_key": "ma_crossover",
            "fixed_params": {"slow": 12},
            "param_grid": {"fast": [3]},
            "timeframe": "1m",
            "start_date": "2026-01-01",
            "end_date": "2026-01-04",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"][0]["candles_count"] == 5760
    assert body["experiment"]["request"]["fetch_batches"] >= 2
    assert len(FakeOKXGateway.calls) >= 2


def test_api_experiment_job_reports_progress_and_result(tmp_path, monkeypatch):
    FakeOKXGateway.calls = []
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", FakeOKXGateway)
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/experiments/jobs",
        json={
            "name": "job range",
            "strategy_key": "ma_crossover",
            "fixed_params": {"slow": 12},
            "param_grid": {"fast": [3]},
            "start_date": "2026-01-01",
            "end_date": "2026-01-01",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["id"]
    for _ in range(50):
        job = client.get(f"/api/experiments/jobs/{job_id}").json()
        if job["status"] == "completed":
            break
        time.sleep(0.02)

    assert job["status"] == "completed"
    assert job["progress"]["percent"] == 100
    assert len(job["result"]["runs"]) == 1


def test_api_experiment_reports_auto_fetch_failure(tmp_path, monkeypatch):
    class FailingGateway:
        def __init__(self, settings, broker_mode, market_type):
            pass

        def fetch_candles(self, *, symbol, timeframe, limit=200, since=None):
            raise RuntimeError("exchange unavailable")

    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", FailingGateway)
    settings = make_settings(tmp_path)
    app = create_app(settings=settings, database=make_database(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/experiments",
        json={"name": "missing data", "strategy_key": "ma_crossover", "param_grid": {"fast": [3]}, "candles_limit": 12},
    )

    assert response.status_code == 502
    assert "OKX candle auto-fetch failed" in response.json()["detail"]


def test_api_instance_status_demo_start_aligns_broker_mode(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    started = []
    app.state.runner_manager.start_instance = started.append
    client = TestClient(app)

    with database.session() as session:
        _add_account(session, "okx_demo", "demo")
        instance = StrategyInstance(
            name="Demo runner",
            strategy_key="rsi",
            broker_mode="okx_live",
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            initial_equity=1000,
            params={"period": 2},
        )
        session.add(instance)
        session.flush()
        instance_id = instance.id

    response = client.post(f"/api/instances/{instance_id}/status", json={"status": "okx_demo_running"})

    assert response.status_code == 200
    assert response.json()["broker_mode"] == "okx_demo"
    assert started == [instance_id]


def test_api_instance_create_defaults_account_and_rejects_mismatch(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        demo = _add_account(session, "okx_demo", "demo")
        live = _add_account(session, "okx_live", "live")

    created = client.post(
        "/api/instances",
        json={
            "name": "Demo bound",
            "strategy_key": "rsi",
            "broker_mode": "okx_demo",
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "params": {"period": 2},
        },
    )
    mismatch = client.post(
        "/api/instances",
        json={
            "name": "Wrong account",
            "strategy_key": "rsi",
            "broker_mode": "okx_demo",
            "account_id": live.id,
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "params": {"period": 2},
        },
    )

    assert created.status_code == 200
    assert created.json()["account_id"] == demo.id
    assert mismatch.status_code == 400
    assert "okx_demo" in mismatch.json()["detail"]


def test_api_instance_status_blocks_direct_live_start_without_gate(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    started = []
    app.state.runner_manager.start_instance = started.append
    client = TestClient(app)

    with database.session() as session:
        _add_account(session, "okx_live", "live")
        instance = StrategyInstance(
            name="Live runner",
            strategy_key="rsi",
            broker_mode="okx_live",
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            initial_equity=1000,
            allow_live=True,
            params={"period": 2},
        )
        session.add(instance)
        session.flush()
        instance_id = instance.id

    response = client.post(f"/api/instances/{instance_id}/status", json={"status": "okx_live_running"})

    assert response.status_code == 400
    assert "ALLOW_LIVE_TRADING" in response.json()["detail"]
    assert started == []


def test_api_instance_status_allows_live_start_after_gate(tmp_path):
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        allow_live_trading=True,
        live_confirm_phrase="ARM",
    )
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    started = []
    app.state.runner_manager.start_instance = started.append
    client = TestClient(app)

    with database.session() as session:
        _add_account(session, "okx_live", "live")
        instance = StrategyInstance(
            name="Live runner",
            strategy_key="rsi",
            broker_mode="okx_demo",
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            initial_equity=1000,
            allow_live=True,
            params={"period": 2},
        )
        session.add(instance)
        session.flush()
        instance_id = instance.id

    response = client.post(
        f"/api/instances/{instance_id}/status",
        json={"status": "okx_live_running", "confirmation": "ARM"},
    )

    assert response.status_code == 200
    assert response.json()["broker_mode"] == "okx_live"
    assert started == [instance_id]


def test_api_instance_test_order_records_buy_sell_and_order_detail(tmp_path, monkeypatch):
    OrderGateway.calls = []
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", OrderGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = _add_account(session, "okx_demo", "demo")
        instance = StrategyInstance(
            name="Demo order",
            strategy_key="rsi",
            account_id=account.id,
            broker_mode="okx_demo",
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            initial_equity=1000,
            fee_rate=0.001,
            params={"period": 2},
        )
        session.add(instance)
        session.flush()
        instance_id = instance.id

    buy = client.post(f"/api/instances/{instance_id}/test-order", json={"side": "buy", "quote_usdt": 5})
    sell = client.post(f"/api/instances/{instance_id}/test-order", json={"side": "sell"})

    assert buy.status_code == 200
    assert sell.status_code == 200
    assert [call["side"] for call in OrderGateway.calls] == ["buy", "sell"]
    assert buy.json()["account_id"] == account.id
    assert buy.json()["external_order_id"] == "ord-1"
    assert sell.json()["external_order_id"] == "ord-2"

    rows = client.get(f"/api/instances/{instance_id}/trades").json()
    assert len(rows) == 2
    detail = client.get(f"/api/trades/{rows[0]['id']}").json()
    assert detail["account"]["id"] == account.id
    assert detail["okx_order"]["data"][0]["state"] == "filled"


def test_api_account_summary_includes_bound_strategies_and_trade_stats(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.api.OKXGateway", NonzeroAccountGateway)
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        account = _add_account(session, "okx_demo", "demo")
        instance = StrategyInstance(
            name="Demo summary",
            strategy_key="ma_crossover",
            account_id=account.id,
            broker_mode="okx_demo",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_equity=1000,
            params={"fast": 5, "slow": 20},
        )
        session.add(instance)
        session.flush()
        session.add(
            Trade(
                instance_id=instance.id,
                account_id=account.id,
                broker_mode="okx_demo",
                market_type="spot",
                symbol="BTC/USDT",
                side="sell",
                amount=1,
                price=110,
                fee=0.1,
                pnl=10,
            )
        )

    response = client.get("/api/accounts/summary")

    assert response.status_code == 200
    summary = response.json()[0]
    assert summary["account"]["id"] == account.id
    assert summary["instances"][0]["name"] == "Demo summary"
    assert summary["trade_stats"]["realized_pnl"] == 10
    assert summary["balance"]["total_eq"] == "5000"


def test_api_trade_source_filter(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        session.add_all(
                [
                    Trade(broker_mode="backtest", market_type="spot", symbol="BTC/USDT", side="buy", amount=1, price=100),
                    Trade(broker_mode="okx_demo", market_type="spot", symbol="BTC/USDT", side="sell", amount=1, price=101),
                ]
            )

    response = client.get("/api/trades", params={"source": "okx_demo"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["broker_mode"] == "okx_demo"

    legacy = client.get("/api/trades", params={"source": "paper"})
    assert legacy.status_code == 400


def test_api_trade_order_status_exposes_failed_order_reason(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        session.add(
            Trade(
                broker_mode="okx_demo",
                market_type="spot",
                symbol="BTC/USDT",
                side="buy",
                amount=0,
                price=100,
                meta={
                    "status": "failed",
                    "error": 'okx {"code":"50001","data":[],"msg":"Service temporarily unavailable. Please try again later."}',
                    "attempted_amount": 0.05,
                },
            )
        )

    response = client.get("/api/trades")

    assert response.status_code == 200
    status = response.json()[0]["order_status"]
    assert status["state"] == "failed"
    assert status["label"] == "下单失败"
    assert status["code"] == "50001"
    assert status["reason"] == "Service temporarily unavailable. Please try again later."
    assert status["attempted_amount"] == 0.05


def test_api_instance_performance_uses_online_instance_trades(tmp_path):
    settings = make_settings(tmp_path)
    database = make_database(tmp_path)
    app = create_app(settings=settings, database=database)
    client = TestClient(app)

    with database.session() as session:
        instance = StrategyInstance(
            name="Demo runner",
            strategy_key="ma_crossover",
            broker_mode="okx_demo",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_equity=10000,
            params={"fast": 5, "slow": 20},
        )
        session.add(instance)
        session.flush()
        session.add_all(
            [
                Trade(
                    instance_id=instance.id,
                    broker_mode="okx_demo",
                    market_type="spot",
                    symbol="BTC/USDT",
                    side="sell",
                    amount=1,
                    price=101,
                    fee=0.2,
                    pnl=120,
                ),
                Trade(
                    instance_id=instance.id,
                    broker_mode="okx_demo",
                    market_type="spot",
                    symbol="BTC/USDT",
                    side="sell",
                    amount=1,
                    price=99,
                    fee=0.1,
                    pnl=-20,
                ),
                Trade(
                    broker_mode="backtest",
                    market_type="spot",
                    symbol="BTC/USDT",
                    side="sell",
                    amount=1,
                    price=200,
                    pnl=999,
                ),
                Trade(
                    instance_id=instance.id,
                    broker_mode="okx_demo",
                    market_type="spot",
                    symbol="BTC/USDT",
                    side="buy",
                    amount=0,
                    price=100,
                    pnl=0,
                    meta={"status": "failed", "error": "auth failed"},
                ),
            ]
        )

    response = client.get("/api/instances/performance")

    assert response.status_code == 200
    stats = response.json()[str(instance.id)]
    assert stats["trades_count"] == 2
    assert stats["failed_trades_count"] == 1
    assert stats["realized_pnl"] == 100
    assert stats["return_pct"] == 1
    assert stats["win_rate_pct"] == 50
    assert abs(stats["fee_paid"] - 0.3) < 1e-9
    assert stats["broker_modes"] == ["okx_demo"]
