from __future__ import annotations


def sma(values: list[float], window: int) -> float:
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        raise ValueError("not enough values")
    return sum(values[-window:]) / window


def moving_average_signal(closes: list[float], fast: int = 5, slow: int = 20) -> str:
    """Return buy/sell/hold using simple MA crossover.

    Uses previous bar and current bar to detect actual crossovers.
    """
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("require 0 < fast < slow")
    if len(closes) < slow + 1:
        return "hold"

    prev = closes[:-1]
    prev_fast = sma(prev, fast)
    prev_slow = sma(prev, slow)
    curr_fast = sma(closes, fast)
    curr_slow = sma(closes, slow)

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "buy"
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return "sell"
    return "hold"
