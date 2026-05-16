"""多策略模块 - MACD / RSI / 布林带 + 策略注册表。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SignalStrategy(Protocol):
    """策略接口。"""
    name: str
    def signal(self, closes: list[float]) -> str: ...  # buy / sell / hold


# ── MA 交叉 ──────────────────────────────────────────────────

@dataclass
class MACrossover:
    name: str = "ma_crossover"
    fast: int = 5
    slow: int = 20

    def signal(self, closes: list[float]) -> str:
        from okx_paper_bot.strategy import moving_average_signal
        return moving_average_signal(closes, fast=self.fast, slow=self.slow)


# ── MACD ─────────────────────────────────────────────────────

def _ema(values: list[float], span: int) -> list[float]:
    """计算 EMA 序列。"""
    if not values:
        return []
    k = 2 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


@dataclass
class MACDStrategy:
    name: str = "macd"
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def signal(self, closes: list[float]) -> str:
        need = self.slow_period + self.signal_period + 1
        if len(closes) < need:
            return "hold"

        fast_ema = _ema(closes, self.fast_period)
        slow_ema = _ema(closes, self.slow_period)
        macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
        signal_line = _ema(macd_line, self.signal_period)

        if len(macd_line) < 2 or len(signal_line) < 2:
            return "hold"

        # 金叉: MACD 从下穿上 signal
        if macd_line[-2] <= signal_line[-2] and macd_line[-1] > signal_line[-1]:
            return "buy"
        # 死叉: MACD 从上穿下 signal
        if macd_line[-2] >= signal_line[-2] and macd_line[-1] < signal_line[-1]:
            return "sell"
        return "hold"


# ── RSI ──────────────────────────────────────────────────────

def _rsi(closes: list[float], period: int = 14) -> float:
    """计算最新 RSI 值。"""
    if len(closes) < period + 1:
        return 50.0  # 中性
    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@dataclass
class RSIStrategy:
    name: str = "rsi"
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def signal(self, closes: list[float]) -> str:
        if len(closes) < self.period + 1:
            return "hold"
        rsi = _rsi(closes, self.period)
        if rsi <= self.oversold:
            return "buy"
        if rsi >= self.overbought:
            return "sell"
        return "hold"


# ── 布林带 ───────────────────────────────────────────────────

@dataclass
class BollingerStrategy:
    name: str = "bollinger"
    period: int = 20
    std_dev: float = 2.0

    def signal(self, closes: list[float]) -> str:
        if len(closes) < self.period:
            return "hold"
        window = closes[-self.period:]
        mean = sum(window) / self.period
        var = sum((x - mean) ** 2 for x in window) / self.period
        std = var ** 0.5
        upper = mean + self.std_dev * std
        lower = mean - self.std_dev * std
        price = closes[-1]
        if price <= lower:
            return "buy"   # 触及下轨，超卖
        if price >= upper:
            return "sell"  # 触及上轨，超买
        return "hold"


# ── 策略注册表 ───────────────────────────────────────────────

STRATEGIES: dict[str, type] = {
    "ma_crossover": MACrossover,
    "macd": MACDStrategy,
    "rsi": RSIStrategy,
    "bollinger": BollingerStrategy,
}


def get_strategy(name: str, **kwargs) -> SignalStrategy:
    """按名称获取策略实例。"""
    cls = STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"未知策略: {name}，可选: {list(STRATEGIES.keys())}")
    return cls(**kwargs)
