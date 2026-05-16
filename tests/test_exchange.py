"""Tests for okx_paper_bot.exchange module."""
import pytest
from okx_paper_bot.exchange import FakeExchange, retry_call, create_okx_exchange, fetch_close_prices
from okx_paper_bot.config import BotConfig


class TestFakeExchange:
    def test_fetch_ohlcv_returns_candles(self):
        candles = [[1, 2, 3, 4, 100.0], [5, 6, 7, 8, 200.0]]
        ex = FakeExchange(candles=candles)
        assert len(ex.fetch_ohlcv("BTC/USDT", "1m")) == 2
    def test_fetch_ohlcv_with_limit(self):
        candles = [[1, 2, 3, 4, 100.0], [5, 6, 7, 8, 200.0], [9, 10, 11, 12, 300.0]]
        ex = FakeExchange(candles=candles)
        result = ex.fetch_ohlcv("BTC/USDT", "1m", limit=2)
        assert len(result) == 2
        assert result[0][4] == 200.0
    def test_records_calls(self):
        ex = FakeExchange(candles=[[1, 2, 3, 4, 100.0]])
        ex.fetch_ohlcv("ETH/USDT", "5m", limit=10)
        assert ex.calls == [("ETH/USDT", "5m", 10)]
    def test_default_options(self):
        assert FakeExchange().options["defaultType"] == "spot"


class TestRetryCall:
    def test_success_first_try(self):
        assert retry_call(lambda: 42) == 42
    def test_retries_on_failure(self):
        attempts = []
        def fn():
            attempts.append(1)
            if len(attempts) < 3: raise RuntimeError("fail")
            return "ok"
        assert retry_call(fn, attempts=3, delay_seconds=0) == "ok"
        assert len(attempts) == 3
    def test_raises_after_all_attempts(self):
        with pytest.raises(RuntimeError):
            retry_call(lambda: (_ for _ in ()).throw(RuntimeError("fail")), attempts=2, delay_seconds=0)


class TestFetchClosePrices:
    def test_extracts_close_prices(self):
        candles = [[0, 1, 2, 3, 29300.0], [0, 1, 2, 3, 29600.0], [0, 1, 2, 3, 29900.0]]
        ex = FakeExchange(candles=candles)
        assert fetch_close_prices(ex, "BTC/USDT", "1m", limit=3) == [29300.0, 29600.0, 29900.0]


class TestCreateOkxExchange:
    def test_create_exchange_returns_exchange(self):
        exchange = create_okx_exchange(BotConfig())
        assert exchange is not None
    def test_demo_header_set(self):
        exchange = create_okx_exchange(BotConfig(okx_demo=True))
        assert exchange.headers.get("x-simulated-trading") == "1"
    def test_no_demo_header(self):
        exchange = create_okx_exchange(BotConfig(okx_demo=False))
        assert "x-simulated-trading" not in exchange.headers
