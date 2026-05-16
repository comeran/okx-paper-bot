"""Tests for exchange."""
from okx_paper_bot.exchange import FakeExchange, retry_call, create_okx_exchange, fetch_close_prices
from okx_paper_bot.config import BotConfig

class TestFakeExchange:
    def test_fetch(self):
        assert len(FakeExchange(candles=[[1,2,3,4,100.0],[5,6,7,8,200.0]]).fetch_ohlcv("BTC/USDT","1m")) == 2
    def test_calls(self):
        ex = FakeExchange(candles=[[1,2,3,4,100.0]]); ex.fetch_ohlcv("ETH/USDT","5m",limit=10)
        assert ex.calls == [("ETH/USDT","5m",10)]

class TestRetryCall:
    def test_success(self): assert retry_call(lambda: 42) == 42

class TestFetchClosePrices:
    def test_extract(self):
        assert fetch_close_prices(FakeExchange(candles=[[0,1,2,3,100.0],[0,1,2,3,200.0]]), "BTC/USDT", "1m", 2) == [100.0, 200.0]

class TestCreateOkxExchange:
    def test_returns(self): assert create_okx_exchange(BotConfig()) is not None
    def test_demo(self): assert create_okx_exchange(BotConfig(okx_demo=True)).headers.get("x-simulated-trading") == "1"
