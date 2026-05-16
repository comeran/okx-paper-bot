"""Tests for strategy."""
import pytest
from okx_paper_bot.strategy import sma, ema, rsi, bollinger_bands, moving_average_signal, rsi_signal, bollinger_signal, get_signal

class TestSMA:
    def test_basic(self): assert sma([1,2,3,4,5], 3) == 4.0
    def test_window(self): assert sma([10,20,30], 3) == 20.0
    def test_single(self): assert sma([42.0], 1) == 42.0
    def test_zero(self):
        with pytest.raises(ValueError): sma([1,2,3], 0)
    def test_short(self):
        with pytest.raises(ValueError): sma([1,2], 3)

class TestEMA:
    def test_basic(self): assert ema([1,2,3,4,5], 3) > 0
    def test_zero(self):
        with pytest.raises(ValueError): ema([1,2,3], 0)

class TestRSI:
    def test_neutral(self): assert rsi([50.0]*20, 14) == 50.0
    def test_short(self): assert rsi([1.0]*5, 14) == 50.0
    def test_up(self): assert rsi([100.0+i for i in range(20)], 14) > 50
    def test_down(self): assert rsi([100.0-i for i in range(20)], 14) < 50

class TestBollinger:
    def test_constant(self):
        u, m, l = bollinger_bands([100.0]*20, 20, 2.0)
        assert u == 100.0 and m == 100.0 and l == 100.0
    def test_short(self):
        with pytest.raises(ValueError): bollinger_bands([1.0]*5, 20)

class TestMASignal:
    def test_hold(self): assert moving_average_signal([100.0]*25) == "hold"
    def test_buy(self): assert moving_average_signal([100.0]*24+[200.0]) == "buy"
    def test_sell(self): assert moving_average_signal([100.0]*24+[10.0]) == "sell"

class TestRSISignal:
    def test_hold(self): assert rsi_signal([50.0]*20) == "hold"

class TestBollingerSignal:
    def test_hold(self): assert bollinger_signal([100.0]*25) == "hold"

class TestGetSignal:
    def test_ma(self): assert get_signal([100.0]*25, "ma_crossover") == "hold"
    def test_rsi(self): assert get_signal([100.0]*25, "rsi") == "hold"
    def test_bollinger(self): assert get_signal([100.0]*25, "bollinger") == "hold"
    def test_unknown(self):
        with pytest.raises(ValueError): get_signal([1.0]*25, "xxx")
