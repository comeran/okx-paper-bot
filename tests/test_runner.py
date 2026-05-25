from okx_paper_bot.config import AppSettings
from okx_paper_bot.market import MarketDataService
from okx_paper_bot.persistence.models import AccountConfig, AuditEvent, StrategyInstance, Trade
from okx_paper_bot.runner import RunnerManager, StrategyRunner
from okx_paper_bot.strategies import OrderIntent
from tests.conftest import make_database, make_settings


class _InsufficientDemoGateway:
    def __init__(self, settings, broker_mode, market_type):
        pass

    def place_order(self, **kwargs):
        raise RuntimeError('okx {"code":"51008","msg":"Order failed. Your available balance is insufficient."}')


def _create_instance(database):
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
        instance = StrategyInstance(
            name="Demo RSI",
            strategy_key="rsi",
            account_id=account.id,
            broker_mode="okx_demo",
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            initial_equity=1000,
            order_usdt=500,
            fee_rate=0.001,
            slippage_rate=0.0,
            params={"period": 7},
            status="okx_demo_running",
        )
        session.add(instance)
        session.commit()
        return instance.id


def test_demo_order_reports_exchange_error_when_demo_balance_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("okx_paper_bot.runner.OKXGateway", _InsufficientDemoGateway)
    database = make_database(tmp_path)
    instance_id = _create_instance(database)
    runner = StrategyRunner(instance_id, make_settings(tmp_path), database, MarketDataService())
    runner._state = {"cash": 1000.0, "position_size": 0.0, "avg_entry_price": 0.0, "last_price": 0.0}

    fill, error = runner._execute(
        OrderIntent(side="buy", quote_amount=500, reason="rsi"),
        "okx_demo",
        "BTC/USDT",
        "spot",
        100.0,
    )

    assert fill is None
    assert error is not None
    assert "available balance is insufficient" in error

    runner._record_failed_trade(OrderIntent(side="buy", quote_amount=500, reason="rsi"), "BTC/USDT", "spot", "okx_demo", 100.0, error)
    runner._pause_instance_after_order_error(error, "okx_demo")

    with database.session() as session:
        instance = session.get(StrategyInstance, instance_id)
        audit = session.query(AuditEvent).filter(AuditEvent.action == "instance.auto_pause").one()
        trade = session.query(Trade).one()
        assert instance.status == "paused"
        assert audit.meta["fatal"] is False
        assert "available balance is insufficient" in trade.meta["error"]
        assert trade.meta["status"] == "failed"
        assert trade.amount == 0
        assert trade.meta["attempted_amount"] == 5


def test_order_error_pauses_instance_after_failed_trade(tmp_path):
    database = make_database(tmp_path)
    instance_id = _create_instance(database)
    runner = StrategyRunner(instance_id, make_settings(tmp_path), database, MarketDataService())
    error = 'okx {"msg":"Invalid OK-ACCESS-KEY","code":"50111"}'

    runner._record_failed_trade(OrderIntent(side="buy", quote_amount=500, reason="rsi"), "BTC/USDT", "spot", "okx_demo", 100.0, error)
    runner._pause_instance_after_order_error(error, "okx_demo")

    with database.session() as session:
        instance = session.get(StrategyInstance, instance_id)
        audit = session.query(AuditEvent).filter(AuditEvent.action == "instance.auto_pause").one()
        trade = session.query(Trade).one()
        assert instance.status == "paused"
        assert audit.meta["fatal"] is True
        assert trade.meta["status"] == "failed"
        assert trade.amount == 0
        assert trade.meta["attempted_amount"] == 5


def test_runner_manager_updates_active_runner_settings(tmp_path):
    database = make_database(tmp_path)
    old = make_settings(tmp_path)
    new = AppSettings(database_url=old.database_url, okx_api_key="new-key")
    manager = RunnerManager(old, database, MarketDataService())
    runner = StrategyRunner(1, old, database, MarketDataService())
    manager._runners[1] = runner

    manager.update_settings(new)

    assert manager.settings.okx_api_key == "new-key"
    assert runner.settings.okx_api_key == "new-key"


def test_restore_running_instances_skips_disabled_rows(tmp_path):
    database = make_database(tmp_path)
    with database.session() as session:
        disabled = StrategyInstance(
            name="disabled stale runner",
            strategy_key="ma_crossover",
            enabled=False,
            status="okx_demo_running",
            broker_mode="okx_demo",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_equity=1000,
            params={},
        )
        enabled = StrategyInstance(
            name="enabled runner",
            strategy_key="ma_crossover",
            enabled=True,
            status="okx_demo_running",
            broker_mode="okx_demo",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_equity=1000,
            params={},
        )
        session.add_all([disabled, enabled])
        session.flush()
        disabled_id = disabled.id
        enabled_id = enabled.id

    manager = RunnerManager(make_settings(tmp_path), database, MarketDataService())
    started = []
    manager.start_instance = started.append

    manager.restore_running_instances()

    assert started == [enabled_id]
    assert disabled_id not in started
    with database.session() as session:
        assert session.get(StrategyInstance, disabled_id).status == "paused"
