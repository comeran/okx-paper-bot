"""Tests for okx_paper_bot.exchange module."""
import pytest
from okx_paper_bot.exchange import FakeExchange, retry_call, create_okx_exchange, fetch_close_prices
from okx_paper_bot.config import BotConfig


class TestFakeExchange:
    def test_fetch_ohlcv_returns_candles(self):
        candles = [[1, 2, 3, 4, 100.0], [5, 6, 7, 8, 200.0]]
        ex = FakeExchange(candles=candles)
        result = ex.fetch_ohlcv("BTC/USDT", "1m")
        assert len(result) == 2
        assert result[0][4] == 100.0

    def test_fetch_ohlcv_with_limit(self):
        candles = [[1, 2, 3, 4, 100.0], [5, 6, 7, 8, 200.0], [9, 10, 11, 12, 300.0]]
        ex = FakeExchange(candles=candles)
        result = ex.fetch_ohlcv("BTC/USDT", "1m", limit=2)
        assert len(result) == 2
        assert result[0][4] == 200.0
        assert result[1][4] == 300.0

    def test_records_calls(self):
        ex = FakeExchange(candles=[[1, 2, 3, 4, 100.0]])
        ex.fetch_ohlcv("ETH/USDT", "5m", limit=10)
        assert ex.calls == [("ETH/USDT", "5m", 10)]

    def test_default_options(self):
        ex = FakeExchange()
        assert ex.options["defaultType"] == "spot"


class TestRetryCall:
    def test_success_first_try(self):
        assert retry_call(lambda: 42) == 42

    def test_retries_on_failure(self):
        attempts = []
        def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("fail")
            return "ok"
        result = retry_call(fn, attempts=3, delay_seconds=0)
        assert result == "ok"
        assert len(attempts) == 3

    def test_raises_after_all_attempts(self):
        with pytest.raises(RuntimeError, match="always fail"):
            retry_call(lambda: (_ for _ in ()).throw(RuntimeError("always fail")), attempts=2, delay_seconds=0)

    def test_returns_value(self):
        assert retry_call(lambda: "hello") == "hello"


class TestFetchClosePrices:
    def test_extracts_close_prices(self):
        candles = [
            [1609459200000, 29000, 29500, 28500, 29300, 100],
            [1609459260000, 29300, 29800, 29100, 29600, 120],
            [1609459320000, 29600, 30000, 29400, 29900, 90],
        ]
        ex = FakeExchange(candles=candles)
        prices = fetch_close_prices(ex, "BTC/USDT", "1m", limit=3)
        assert prices == [29300.0, 29600.0, 29900.0]


class TestCreateOkxExchange:
    def test_without_ccxt_returns_fake(self):
        config = BotConfig()
        exchange = create_okx_exchange(config)
        assert isinstance(exchange, FakeExchange)

    def test_demo_header_set(self):
        config = BotConfig(okx_demo=True)
        exchange = create_okx_exchange(config)
        assert exchange.headers.get("x-simulated-trading") == "1"

    def test_no_demo_header(self):
        config = BotConfig(okx_demo=False)
        exchange = create_okx_exchange(config)
        assert "x-simulated-trading" not in exchange.headers
