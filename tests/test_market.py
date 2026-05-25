from datetime import datetime, timezone

from okx_paper_bot.market import CandleData, MarketDataService


def test_candle_cache_filters_unfinished_candles(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()

    with database.session() as session:
        service.upsert_candles(
            session,
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1m",
            candles=[
                CandleData(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 2, 1, 2, completed=True),
                CandleData(datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), 2, 3, 2, 3, completed=False),
            ],
            source="test",
        )
        candles = service.list_candles(
            session, market_type="spot", symbol="BTC/USDT", timeframe="1m", completed_only=True
        )

    assert len(candles) == 1
    assert candles[0].close == 2


def test_seed_sample_is_queryable(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()

    with database.session() as session:
        inserted = service.seed_sample(session, count=12)
        candles = service.list_candles(session, market_type="spot", symbol="BTC/USDT", timeframe="1h")

    assert inserted == 12
    assert len(candles) == 12


def test_upsert_matches_existing_candles_after_reload(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with database.session() as session:
        service.upsert_candles(
            session,
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1h",
            candles=[CandleData(ts, 1, 2, 1, 2, completed=True)],
            source="test",
        )

    with database.session() as session:
        service.upsert_candles(
            session,
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1h",
            candles=[CandleData(ts, 2, 3, 2, 3, completed=True)],
            source="okx",
        )
        candles = service.list_candles(session, market_type="spot", symbol="BTC/USDT", timeframe="1h")

    assert len(candles) == 1
    assert candles[0].close == 3


def test_upsert_deduplicates_candles_with_same_timestamp_in_one_batch(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    service = MarketDataService()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with database.session() as session:
        service.upsert_candles(
            session,
            market_type="spot",
            symbol="BTC/USDT",
            timeframe="1h",
            candles=[
                CandleData(ts, 1, 2, 1, 2, completed=True),
                CandleData(ts, 2, 4, 2, 4, completed=True),
            ],
            source="okx",
        )
        candles = service.list_candles(session, market_type="spot", symbol="BTC/USDT", timeframe="1h")

    assert len(candles) == 1
    assert candles[0].close == 4
