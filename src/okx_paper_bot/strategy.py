from __future__ import annotations

import math


def sma(values: list[float], window: int) -> float:
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        raise ValueError("not enough values")
    return sum(values[-window:]) / window


def ema(values: list[float], period: int) -> float:
    """指数移动平均。"""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError("not enough values")
    k = 2 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1 - k)
    return result


def rsi(closes: list[float], period: int = 14) -> float:
    """相对强弱指数 (RSI)。返回 0~100。"""
    if len(closes) < period + 1:
        return 50.0  # 数据不足返回中性值
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0 and avg_gain == 0:
        return 50.0  # 无涨跌 -> 中性
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def bollinger_bands(closes: list[float], period: int = 20, num_std: float = 2.0) -> tuple[float, float, float]:
    """布林带。返回 (upper, middle, lower)。"""
    if len(closes) < period:
        raise ValueError("not enough values")
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = math.sqrt(variance)
    return middle + num_std * std, middle, middle - num_std * std


# ---- 信号生成器 ----

def moving_average_signal(closes: list[float], fast: int = 5, slow: int = 20) -> str:
    """MA 交叉: buy/sell/hold。"""
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


def rsi_signal(closes: list[float], period: int = 14, buy_threshold: float = 30.0, sell_threshold: float = 70.0) -> str:
    """RSI 超买超卖: buy/sell/hold。"""
    val = rsi(closes, period)
    if val <= buy_threshold:
        return "buy"
    if val >= sell_threshold:
        return "sell"
    return "hold"


def bollinger_signal(closes: list[float], period: int = 20, num_std: float = 2.0) -> str:
    """布林带突破: 价格跌破下轨买，突破上轨卖。"""
    if len(closes) < period:
        return "hold"
    upper, middle, lower = bollinger_bands(closes, period, num_std)
    price = closes[-1]
    if upper == lower:
        return "hold"  # 无波动 -> 不触发
    if price <= lower:
        return "buy"
    if price >= upper:
        return "sell"
    return "hold"


def get_signal(closes: list[float], strategy: str = "ma_crossover", **kwargs) -> str:
    """策略调度器。"""
    if strategy == "ma_crossover":
        return moving_average_signal(closes, fast=kwargs.get("fast", 5), slow=kwargs.get("slow", 20))
    elif strategy == "rsi":
        return rsi_signal(closes, period=kwargs.get("period", 14),
                          buy_threshold=kwargs.get("buy_threshold", 30.0),
                          sell_threshold=kwargs.get("sell_threshold", 70.0))
    elif strategy == "bollinger":
        return bollinger_signal(closes, period=kwargs.get("period", 20),
                                num_std=kwargs.get("num_std", 2.0))
    else:
        raise ValueError(f"unknown strategy: {strategy}")
