from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    order_usdt: float = 100.0
    max_position_fraction: float = 0.25


@dataclass(frozen=True)
class StopLossConfig:
    """止损止盈配置。

    stop_loss_pct: 止损百分比 (0.05 = 亏5%触发)
    take_profit_pct: 止盈百分比 (0.10 = 盈10%触发)
    trailing_stop_pct: 移动止损百分比 (0.03 = 从最高点回撤3%触发)，0 表示不启用
    """
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.0


def size_order(balance_usdt: float, price: float, config: RiskConfig) -> float:
    """Return base-asset quantity capped by max position fraction."""
    if price <= 0 or balance_usdt <= 0:
        return 0.0
    allowed_usdt = min(config.order_usdt, balance_usdt * config.max_position_fraction)
    if allowed_usdt <= 0:
        return 0.0
    return allowed_usdt / price


def check_stop_loss(
    entry_price: float,
    current_price: float,
    highest_price: float,
    config: StopLossConfig,
) -> str | None:
    """检查是否触发止损/止盈。

    返回: 'stop_loss' / 'take_profit' / 'trailing_stop' / None
    """
    if entry_price <= 0 or current_price <= 0:
        return None

    # 止损: 价格跌破入场价的 (1 - stop_loss_pct)
    if current_price <= entry_price * (1 - config.stop_loss_pct):
        return "stop_loss"

    # 止盈: 价格涨过入场价的 (1 + take_profit_pct)
    if current_price >= entry_price * (1 + config.take_profit_pct):
        return "take_profit"

    # 移动止损: 价格从最高点回撤超过 trailing_stop_pct
    if config.trailing_stop_pct > 0 and highest_price > 0:
        if current_price <= highest_price * (1 - config.trailing_stop_pct):
            return "trailing_stop"

    return None
