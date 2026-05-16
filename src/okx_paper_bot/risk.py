from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    order_usdt: float = 100.0
    max_position_fraction: float = 0.25


def size_order(balance_usdt: float, price: float, config: RiskConfig) -> float:
    """Return base-asset quantity capped by max position fraction."""
    if price <= 0 or balance_usdt <= 0:
        return 0.0
    allowed_usdt = min(config.order_usdt, balance_usdt * config.max_position_fraction)
    if allowed_usdt <= 0:
        return 0.0
    return allowed_usdt / price
