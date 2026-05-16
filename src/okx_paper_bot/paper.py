from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count


@dataclass
class PaperAccount:
    balance_usdt: float = 1_000.0
    positions: dict[str, float] = field(default_factory=dict)
    _ids: count = field(default_factory=lambda: count(1), init=False, repr=False)

    def execute_market_order(self, symbol: str, side: str, amount: float, price: float) -> dict:
        order = {
            "id": f"paper-{next(self._ids)}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "status": "closed",
        }
        if amount <= 0 or price <= 0:
            order["status"] = "rejected"
            return order

        notional = amount * price
        if side == "buy":
            if notional > self.balance_usdt:
                order["status"] = "rejected"
                return order
            self.balance_usdt -= notional
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
            return order

        if side == "sell":
            held = self.positions.get(symbol, 0.0)
            if amount > held:
                order["status"] = "rejected"
                return order
            self.balance_usdt += notional
            remaining = held - amount
            if remaining:
                self.positions[symbol] = remaining
            else:
                self.positions.pop(symbol, None)
            return order

        order["status"] = "rejected"
        return order
