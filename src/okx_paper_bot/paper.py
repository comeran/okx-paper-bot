from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count


@dataclass
class PaperAccount:
    balance_usdt: float = 1_000.0
    positions: dict[str, float] = field(default_factory=dict)
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    _ids: count = field(default_factory=lambda: count(1), init=False, repr=False)
    _pending_orders: list[dict] = field(default_factory=list, init=False, repr=False)

    def execute_market_order(self, symbol: str, side: str, amount: float, price: float) -> dict:
        """执行市价单（含手续费和滑点）。"""
        order = {
            "id": f"paper-{next(self._ids)}", "symbol": symbol, "side": side,
            "amount": amount, "price": price, "status": "closed", "type": "market",
        }
        if amount <= 0 or price <= 0:
            order["status"] = "rejected"
            return order

        # 滑点: 买入价更高，卖出价更低
        if side == "buy":
            exec_price = price * (1 + self.slippage_pct)
        elif side == "sell":
            exec_price = price * (1 - self.slippage_pct)
        else:
            order["status"] = "rejected"
            return order

        notional = amount * exec_price
        fee = notional * self.fee_pct

        if side == "buy":
            total_cost = notional + fee
            if total_cost > self.balance_usdt:
                order["status"] = "rejected"
                return order
            self.balance_usdt -= total_cost
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
            order["price"] = exec_price
            order["fee"] = fee
            return order

        if side == "sell":
            held = self.positions.get(symbol, 0.0)
            if amount > held:
                order["status"] = "rejected"
                return order
            self.balance_usdt += notional - fee
            remaining = held - amount
            if remaining:
                self.positions[symbol] = remaining
            else:
                self.positions.pop(symbol, None)
            order["price"] = exec_price
            order["fee"] = fee
            return order

        order["status"] = "rejected"
        return order

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float) -> dict:
        """挂限价单（不立即成交，等待触发）。"""
        order = {
            "id": f"limit-{next(self._ids)}", "symbol": symbol, "side": side,
            "amount": amount, "price": price, "status": "pending", "type": "limit",
        }
        if amount <= 0 or price <= 0:
            order["status"] = "rejected"
            return order
        self._pending_orders.append(order)
        return order

    def check_pending_orders(self, symbol: str, current_price: float) -> list[dict]:
        """检查限价单是否触发。返回已成交订单列表。"""
        filled = []
        remaining = []
        for order in self._pending_orders:
            if order["symbol"] != symbol:
                remaining.append(order)
                continue
            triggered = False
            if order["side"] == "buy" and current_price <= order["price"]:
                triggered = True
            elif order["side"] == "sell" and current_price >= order["price"]:
                triggered = True
            if triggered:
                result = self.execute_market_order(symbol, order["side"], order["amount"], order["price"])
                result["id"] = order["id"]
                result["type"] = "limit"
                filled.append(result)
            else:
                remaining.append(order)
        self._pending_orders = remaining
        return filled

    def cancel_all_pending(self, symbol: str | None = None) -> int:
        """取消挂单。返回取消数量。"""
        before = len(self._pending_orders)
        if symbol:
            self._pending_orders = [o for o in self._pending_orders if o["symbol"] != symbol]
        else:
            self._pending_orders.clear()
        return before - len(self._pending_orders)
