"""模拟账户 - 多仓位管理 + 部分止盈 + 限价单 + 手续费滑点。"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count


@dataclass
class Position:
    """单个仓位（一次买入记录）。"""
    symbol: str
    amount: float
    entry_price: float
    entry_time: str = ""

    @property
    def cost(self) -> float:
        return self.amount * self.entry_price


@dataclass
class PaperAccount:
    balance_usdt: float = 1_000.0
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    _ids: count = field(default_factory=lambda: count(1), init=False, repr=False)
    _positions: list[Position] = field(default_factory=list, init=False, repr=False)
    _pending_orders: list[dict] = field(default_factory=list, init=False, repr=False)

    @property
    def positions(self) -> dict[str, float]:
        """汇总持仓（兼容旧接口）。"""
        result: dict[str, float] = {}
        for p in self._positions:
            result[p.symbol] = result.get(p.symbol, 0.0) + p.amount
        return {k: v for k, v in result.items() if v > 1e-12}

    def get_positions(self, symbol: str) -> list[Position]:
        """获取某交易对的所有仓位（按入场价排序）。"""
        return sorted([p for p in self._positions if p.symbol == symbol and p.amount > 1e-12],
                      key=lambda p: p.entry_price)

    def total_held(self, symbol: str) -> float:
        return sum(p.amount for p in self._positions if p.symbol == symbol and p.amount > 1e-12)

    def avg_entry_price(self, symbol: str) -> float:
        """加权平均入场价。"""
        ps = [p for p in self._positions if p.symbol == symbol and p.amount > 1e-12]
        if not ps:
            return 0.0
        total_cost = sum(p.cost for p in ps)
        total_amount = sum(p.amount for p in ps)
        return total_cost / total_amount if total_amount > 0 else 0.0

    def execute_market_order(self, symbol: str, side: str, amount: float, price: float,
                             time: str = "") -> dict:
        order = {
            "id": f"paper-{next(self._ids)}", "symbol": symbol, "side": side,
            "amount": amount, "price": price, "status": "closed", "type": "market",
        }
        if amount <= 0 or price <= 0:
            order["status"] = "rejected"
            return order

        exec_price = price * (1 + self.slippage_pct if side == "buy" else 1 - self.slippage_pct)
        notional = amount * exec_price
        fee = notional * self.fee_pct

        if side == "buy":
            total_cost = notional + fee
            if total_cost > self.balance_usdt:
                order["status"] = "rejected"
                return order
            self.balance_usdt -= total_cost
            self._positions.append(Position(symbol=symbol, amount=amount, entry_price=exec_price, entry_time=time))
            order["price"] = exec_price
            order["fee"] = fee
            return order

        if side == "sell":
            held = self.total_held(symbol)
            if amount > held + 1e-12:
                order["status"] = "rejected"
                return order
            self.balance_usdt += notional - fee
            order["price"] = exec_price
            order["fee"] = fee
            self._reduce_positions(symbol, amount)
            return order

        order["status"] = "rejected"
        return order

    def _reduce_positions(self, symbol: str, amount: float) -> None:
        """FIFO 减仓。"""
        remaining = amount
        new_positions = []
        for p in self._positions:
            if p.symbol != symbol or p.amount <= 1e-12:
                new_positions.append(p)
                continue
            if remaining <= 1e-12:
                new_positions.append(p)
                continue
            if p.amount <= remaining + 1e-12:
                remaining -= p.amount
                # fully closed, skip
            else:
                p.amount -= remaining
                remaining = 0.0
                new_positions.append(p)
        self._positions = new_positions

    def close_partial(self, symbol: str, fraction: float, price: float, time: str = "") -> list[dict]:
        """部分止盈：按比例平仓所有仓位。

        fraction: 0.5 = 平一半
        返回: 每个仓位的平仓订单列表
        """
        if fraction <= 0 or fraction > 1:
            return []
        orders = []
        for p in self.get_positions(symbol):
            close_amount = p.amount * fraction
            if close_amount < 1e-12:
                continue
            order = self.execute_market_order(symbol, "sell", close_amount, price, time)
            if order["status"] == "closed":
                orders.append(order)
        return orders

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float) -> dict:
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
        before = len(self._pending_orders)
        if symbol:
            self._pending_orders = [o for o in self._pending_orders if o["symbol"] != symbol]
        else:
            self._pending_orders.clear()
        return before - len(self._pending_orders)
