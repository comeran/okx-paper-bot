"""Tests for okx_paper_bot.exchange module."""
import pytest
from okx_paper_bot.exchange import FakeExchange, retry_call, fetch_close_prices


class TestFakeExchange:
    def test_fetch_returns_candles(self):
        fx = FakeExchange(candles=[[0, 0, 0, 0, 100.0], [0, 0, 0, 0, 101.0]])
        result = fx.fetch_ohlcv("BTC/USDT", "1m", limit=2)
        assert len(result) == 2
        assert result[-1][4] == 101.0

    def test_tracks_calls(self):
        fx = FakeExchange(candles=[[0, 0, 0, 0, 50.0]] * 3)
        fx.fetch_ohlcv("ETH/USDT", "5m", limit=3)
        assert fx.calls == [("ETH/USDT", "5m", 3)]


class TestRetryCall:
    def test_succeeds_first_try(self):
        assert retry_call(lambda: 42) == 42

    def test_retries_on_failure(self):
        attempts = 0
        def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("transient")
            return "ok"
        assert retry_call(flaky, attempts=3, delay_seconds=0) == "ok"
        assert attempts == 3

    def test_raises_after_all_failures(self):
        with pytest.raises(RuntimeError, match="permanent"):
            retry_call(lambda: (_ for _ in ()).throw(RuntimeError("permanent")), attempts=2, delay_seconds=0)


class TestFetchClosePrices:
    def test_extracts_close(self):
        candles = [
            [0, 0, 0, 0, 100.0],
            [0, 0, 0, 0, 200.0],
            [0, 0, 0, 0, 300.0],
        ]
        fx = FakeExchange(candles=candles)
        closes = fetch_close_prices(fx, "BTC/USDT", "1m", limit=3, delay_seconds=0)
        assert closes == [100.0, 200.0, 300.0]
