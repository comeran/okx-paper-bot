from okx_paper_bot.backtest import EventBacktester
from okx_paper_bot.market import MarketDataService


def test_event_backtest_runs_against_completed_candles(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()

    with database.session() as session:
        service.seed_sample(session, count=120)
        candles = service.list_candles(session, market_type="spot", symbol="BTC/USDT", timeframe="1h")

    result = EventBacktester().run(
        strategy_key="ma_crossover",
        strategy_params={"fast": 3, "slow": 8},
        candles=candles,
        market_type="spot",
        symbol="BTC/USDT",
        timeframe="1h",
    )

    assert result.final_equity > 0
    assert result.metrics["trades_count"] >= 0
    assert result.equity_curve[0].equity == 10000


def test_grid_backtest_can_trade_on_seed_data(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()

    with database.session() as session:
        service.seed_sample(session, count=160)
        candles = service.list_candles(session, market_type="spot", symbol="BTC/USDT", timeframe="1h")

    result = EventBacktester().run(
        strategy_key="grid",
        strategy_params={"lower_price": 59000, "upper_price": 66000, "grid_count": 8},
        candles=candles,
        market_type="spot",
        symbol="BTC/USDT",
        timeframe="1h",
    )

    assert result.metrics["trades_count"] > 0
