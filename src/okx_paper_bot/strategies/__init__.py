"""Strategy registry and built-in strategy implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from okx_paper_bot.market import CandleData


@dataclass(frozen=True)
class OrderIntent:
    side: str
    order_type: str = "market"
    quote_amount: float | None = None
    amount: float | None = None
    limit_price: float | None = None
    reason: str = ""


@dataclass
class StrategyContext:
    candles: list[CandleData]
    position_size: float
    order_usdt: float
    state: dict[str, Any] = field(default_factory=dict)


class Strategy(Protocol):
    key: str
    name: str
    description: str
    param_schema: dict[str, Any]

    def intents(self, context: StrategyContext) -> list[OrderIntent]:
        ...


class SignalStrategy:
    key = ""
    name = ""
    description = ""
    param_schema: dict[str, Any] = {}

    def __init__(self, **params: Any):
        self.params = params

    def signal(self, candles: list[CandleData]) -> str:
        return "hold"

    def intents(self, context: StrategyContext) -> list[OrderIntent]:
        signal = self.signal(context.candles)
        if signal == "buy" and context.position_size <= 1e-12:
            return [OrderIntent(side="buy", quote_amount=context.order_usdt, reason=self.key)]
        if signal == "sell" and context.position_size > 1e-12:
            return [OrderIntent(side="sell", amount=context.position_size, reason=self.key)]
        return []


def closes(candles: list[CandleData]) -> list[float]:
    return [c.close for c in candles]


def sma(values: list[float], window: int) -> float:
    if window <= 0 or len(values) < window:
        raise ValueError("not enough values for SMA")
    return sum(values[-window:]) / window


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int) -> float:
    if len(values) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(-period, 0):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class MACrossoverStrategy(SignalStrategy):
    key = "ma_crossover"
    name = "MA Crossover"
    description = "Fast/slow moving-average crossover trend strategy."
    param_schema = {
        "fast": {"type": "int", "default": 5, "min": 2, "max": 100, "step": 1},
        "slow": {"type": "int", "default": 20, "min": 3, "max": 240, "step": 1},
    }

    def signal(self, candles: list[CandleData]) -> str:
        values = closes(candles)
        fast = int(self.params.get("fast", 5))
        slow = int(self.params.get("slow", 20))
        if fast >= slow or len(values) < slow + 1:
            return "hold"
        prev_fast = sum(values[-fast - 1 : -1]) / fast
        prev_slow = sum(values[-slow - 1 : -1]) / slow
        now_fast = sma(values, fast)
        now_slow = sma(values, slow)
        if prev_fast <= prev_slow and now_fast > now_slow:
            return "buy"
        if prev_fast >= prev_slow and now_fast < now_slow:
            return "sell"
        return "hold"


class RSIStrategy(SignalStrategy):
    key = "rsi"
    name = "RSI Mean Reversion"
    description = "Buy oversold RSI and sell overbought RSI."
    param_schema = {
        "period": {"type": "int", "default": 14, "min": 2, "max": 80, "step": 1},
        "oversold": {"type": "float", "default": 30.0, "min": 5.0, "max": 45.0, "step": 1.0},
        "overbought": {"type": "float", "default": 70.0, "min": 55.0, "max": 95.0, "step": 1.0},
    }

    def signal(self, candles: list[CandleData]) -> str:
        values = closes(candles)
        period = int(self.params.get("period", 14))
        if len(values) < period + 1:
            return "hold"
        value = rsi(values, period)
        if value <= float(self.params.get("oversold", 30.0)):
            return "buy"
        if value >= float(self.params.get("overbought", 70.0)):
            return "sell"
        return "hold"


class MACDStrategy(SignalStrategy):
    key = "macd"
    name = "MACD Trend"
    description = "MACD line crossing signal line."
    param_schema = {
        "fast": {"type": "int", "default": 12, "min": 2, "max": 60, "step": 1},
        "slow": {"type": "int", "default": 26, "min": 5, "max": 160, "step": 1},
        "signal": {"type": "int", "default": 9, "min": 2, "max": 60, "step": 1},
    }

    def signal(self, candles: list[CandleData]) -> str:
        values = closes(candles)
        fast = int(self.params.get("fast", 12))
        slow = int(self.params.get("slow", 26))
        signal_period = int(self.params.get("signal", 9))
        if fast >= slow or len(values) < slow + signal_period + 2:
            return "hold"
        fast_ema = ema_series(values, fast)
        slow_ema = ema_series(values, slow)
        macd_line = [a - b for a, b in zip(fast_ema, slow_ema)]
        signal_line = ema_series(macd_line, signal_period)
        if macd_line[-2] <= signal_line[-2] and macd_line[-1] > signal_line[-1]:
            return "buy"
        if macd_line[-2] >= signal_line[-2] and macd_line[-1] < signal_line[-1]:
            return "sell"
        return "hold"


class BollingerStrategy(SignalStrategy):
    key = "bollinger"
    name = "Bollinger Reversion"
    description = "Buy lower band touches and sell upper band touches."
    param_schema = {
        "period": {"type": "int", "default": 20, "min": 5, "max": 160, "step": 1},
        "std_dev": {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1},
    }

    def signal(self, candles: list[CandleData]) -> str:
        values = closes(candles)
        period = int(self.params.get("period", 20))
        if len(values) < period:
            return "hold"
        window = values[-period:]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        band = variance**0.5 * float(self.params.get("std_dev", 2.0))
        if values[-1] <= mean - band:
            return "buy"
        if values[-1] >= mean + band:
            return "sell"
        return "hold"


class BreakoutStrategy(SignalStrategy):
    key = "breakout"
    name = "Channel Breakout"
    description = "Buy new channel highs and sell new channel lows."
    param_schema = {
        "lookback": {"type": "int", "default": 40, "min": 5, "max": 240, "step": 1},
    }

    def signal(self, candles: list[CandleData]) -> str:
        lookback = int(self.params.get("lookback", 40))
        if len(candles) < lookback + 1:
            return "hold"
        previous = candles[-lookback - 1 : -1]
        if candles[-1].close > max(c.high for c in previous):
            return "buy"
        if candles[-1].close < min(c.low for c in previous):
            return "sell"
        return "hold"


class GridStrategy(SignalStrategy):
    key = "grid"
    name = "Grid"
    description = "Stateful range grid with conservative candle high/low fills."
    param_schema = {
        "lower_price": {"type": "float", "default": 55000.0, "min": 1.0, "max": 500000.0, "step": 10.0},
        "upper_price": {"type": "float", "default": 75000.0, "min": 1.0, "max": 500000.0, "step": 10.0},
        "grid_count": {"type": "int", "default": 12, "min": 2, "max": 200, "step": 1},
    }

    def intents(self, context: StrategyContext) -> list[OrderIntent]:
        if len(context.candles) < 2:
            return []
        lower = float(self.params.get("lower_price", 55000.0))
        upper = float(self.params.get("upper_price", 75000.0))
        count = int(self.params.get("grid_count", 12))
        if lower <= 0 or upper <= lower or count < 2:
            return []
        prev = context.candles[-2]
        current = context.candles[-1]
        step = (upper - lower) / count
        filled = set(context.state.setdefault("filled_levels", []))
        intents: list[OrderIntent] = []
        for idx in range(count + 1):
            level = lower + idx * step
            if prev.close > level >= current.close and idx not in filled:
                filled.add(idx)
                intents.append(
                    OrderIntent(side="buy", order_type="limit", quote_amount=context.order_usdt, limit_price=level, reason="grid_buy")
                )
            elif prev.close < level <= current.close and idx in filled and context.position_size > 1e-12:
                filled.remove(idx)
                sell_amount = min(context.position_size, context.order_usdt / max(level, 1e-12))
                intents.append(
                    OrderIntent(side="sell", order_type="limit", amount=sell_amount, limit_price=level, reason="grid_sell")
                )
        context.state["filled_levels"] = sorted(filled)
        return intents[:3]

class RsiBollingerStrategy(SignalStrategy):
    key = "rsi_bollinger"
    name = "RSI + Bollinger Combo"
    description = "Buy when RSI oversold AND price near lower Bollinger band. Sell when RSI overbought OR price above upper band."
    param_schema = {
        "rsi_period": {"type": "int", "default": 14, "min": 5, "max": 40, "step": 1},
        "oversold": {"type": "float", "default": 30.0, "min": 10.0, "max": 45.0, "step": 1.0},
        "overbought": {"type": "float", "default": 70.0, "min": 55.0, "max": 90.0, "step": 1.0},
        "bb_period": {"type": "int", "default": 20, "min": 5, "max": 60, "step": 1},
        "bb_std": {"type": "float", "default": 2.0, "min": 0.5, "max": 3.5, "step": 0.1},
    }

    def signal(self, candles):
        values = closes(candles)
        rsi_period = int(self.params.get("rsi_period", 14))
        bb_period = int(self.params.get("bb_period", 20))
        required = max(rsi_period + 1, bb_period)
        if len(values) < required:
            return "hold"
        rsi_val = rsi(values, rsi_period)
        oversold = float(self.params.get("oversold", 30.0))
        overbought = float(self.params.get("overbought", 70.0))
        window = values[-bb_period:]
        mean = sum(window) / bb_period
        variance = sum((v - mean) ** 2 for v in window) / bb_period
        band = variance**0.5 * float(self.params.get("bb_std", 2.0))
        if rsi_val <= oversold and values[-1] <= mean - band * 0.8:
            return "buy"
        if rsi_val >= overbought or values[-1] >= mean + band:
            return "sell"
        return "hold"


class MomentumStrategy(SignalStrategy):
    key = "momentum"
    name = "EMA Momentum"
    description = "EMA crossover with RSI filter. Buy on golden cross with RSI confirmation, sell on death cross or RSI overbought."
    param_schema = {
        "fast_ema": {"type": "int", "default": 9, "min": 3, "max": 30, "step": 1},
        "slow_ema": {"type": "int", "default": 21, "min": 10, "max": 60, "step": 1},
        "rsi_period": {"type": "int", "default": 14, "min": 5, "max": 30, "step": 1},
        "rsi_exit": {"type": "float", "default": 75.0, "min": 60.0, "max": 90.0, "step": 1.0},
    }

    def signal(self, candles):
        values = closes(candles)
        fast_p = int(self.params.get("fast_ema", 9))
        slow_p = int(self.params.get("slow_ema", 21))
        rsi_p = int(self.params.get("rsi_period", 14))
        required = max(slow_p + 2, rsi_p + 2)
        if len(values) < required:
            return "hold"
        fast_ema_line = ema_series(values, fast_p)
        slow_ema_line = ema_series(values, slow_p)
        rsi_val = rsi(values, rsi_p)
        rsi_exit = float(self.params.get("rsi_exit", 75.0))
        if fast_ema_line[-2] <= slow_ema_line[-2] and fast_ema_line[-1] > slow_ema_line[-1] and rsi_val > 40:
            return "buy"
        if (fast_ema_line[-2] >= slow_ema_line[-2] and fast_ema_line[-1] < slow_ema_line[-1]) or rsi_val >= rsi_exit:
            return "sell"
        return "hold"


class TripleMAStrategy(SignalStrategy):
    key = "triple_ma"
    name = "Triple MA"
    description = "Three MAs for trend confirmation. Buy when short > medium > long with golden cross. Sell on short death cross below medium."
    param_schema = {
        "short": {"type": "int", "default": 5, "min": 3, "max": 15, "step": 1},
        "medium": {"type": "int", "default": 13, "min": 8, "max": 30, "step": 1},
        "long_ma": {"type": "int", "default": 34, "min": 20, "max": 80, "step": 1},
    }

    def signal(self, candles):
        values = closes(candles)
        s = int(self.params.get("short", 5))
        m = int(self.params.get("medium", 13))
        l = int(self.params.get("long_ma", 34))
        if s >= m or m >= l or len(values) < l + 1:
            return "hold"
        s_now = sma(values, s)
        m_now = sma(values, m)
        l_now = sma(values, l)
        s_prev = sum(values[-s-1:-1]) / s
        m_prev = sum(values[-m-1:-1]) / m
        if s_prev <= m_prev and s_now > m_now and m_now > l_now:
            return "buy"
        if s_prev >= m_prev and s_now < m_now:
            return "sell"
        return "hold"

REGISTRY: dict[str, type[SignalStrategy]] = {
    cls.key: cls
    for cls in [
        MACrossoverStrategy,
        RSIStrategy,
        MACDStrategy,
        BollingerStrategy,
        BreakoutStrategy,
        GridStrategy,
        RsiBollingerStrategy,
        MomentumStrategy,
        TripleMAStrategy,
    ]
}


def create_strategy(key: str, params: dict[str, Any] | None = None) -> SignalStrategy:
    if key not in REGISTRY:
        raise ValueError(f"unknown strategy: {key}")
    return REGISTRY[key](**(params or {}))


def strategy_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": cls.key,
            "name": cls.name,
            "description": cls.description,
            "param_schema": cls.param_schema,
        }
        for cls in REGISTRY.values()
    ]


REGISTRY: dict[str, type[SignalStrategy]] = {
    cls.key: cls
    for cls in [
        MACrossoverStrategy,
        RSIStrategy,
        MACDStrategy,
        BollingerStrategy,
        BreakoutStrategy,
        GridStrategy,
        RsiBollingerStrategy,
        MomentumStrategy,
        TripleMAStrategy,
    ]
}


def create_strategy(key: str, params: dict[str, Any] | None = None) -> SignalStrategy:
    if key not in REGISTRY:
        raise ValueError(f"unknown strategy: {key}")
    return REGISTRY[key](**(params or {}))


def strategy_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": cls.key,
            "name": cls.name,
            "description": cls.description,
            "param_schema": cls.param_schema,
        }
        for cls in REGISTRY.values()
    ]
