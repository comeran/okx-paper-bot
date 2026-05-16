"""网格交易模块 - 区间内自动高抛低吸。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GridConfig:
    """网格配置。"""
    symbol: str = "BTC/USDT"
    lower_price: float = 70000.0   # 网格下界
    upper_price: float = 90000.0   # 网格上界
    grid_count: int = 10           # 网格数量
    order_usdt: float = 500.0      # 每格下单金额

    @property
    def grid_step(self) -> float:
        """每格价格间距。"""
        return (self.upper_price - self.lower_price) / self.grid_count

    def grid_prices(self) -> list[float]:
        """所有网格价格（从低到高）。"""
        step = self.grid_step
        return [self.lower_price + i * step for i in range(self.grid_count + 1)]


@dataclass
class GridLevel:
    """单个网格级别的状态。"""
    price: float
    buy_filled: bool = False     # 买单是否已成交
    sell_filled: bool = False    # 卖单是否已成交
    buy_order_id: str = ""
    sell_order_id: str = ""


@dataclass
class GridState:
    """网格交易状态。"""
    config: GridConfig
    levels: list[GridLevel] = field(default_factory=list)
    total_profit: float = 0.0
    completed_grids: int = 0

    def __post_init__(self):
        if not self.levels:
            prices = self.config.grid_prices()
            self.levels = [GridLevel(price=p) for p in prices]

    def check_signals(self, current_price: float, prev_price: float) -> list[dict]:
        """检查价格变化触发的网格信号。

        Returns:
            list of {"action": "buy"/"sell", "price": float, "level_idx": int}
        """
        signals = []
        step = self.config.grid_step

        for i, level in enumerate(self.levels):
            # 价格从上方穿过网格线 → 买入信号
            if prev_price > level.price >= current_price and not level.buy_filled:
                signals.append({"action": "buy", "price": level.price, "level_idx": i})

            # 价格从下方穿过网格线 → 卖出信号
            if prev_price < level.price <= current_price and level.buy_filled and not level.sell_filled:
                signals.append({"action": "sell", "price": level.price, "level_idx": i})

        return signals

    def mark_buy_filled(self, level_idx: int, order_id: str = "") -> None:
        """标记买单已成交。"""
        self.levels[level_idx].buy_filled = True
        self.levels[level_idx].buy_order_id = order_id
        self.levels[level_idx].sell_filled = False  # 重置卖单状态

    def mark_sell_filled(self, level_idx: int, order_id: str = "") -> None:
        """标记卖单已成交。"""
        self.levels[level_idx].sell_filled = True
        self.levels[level_idx].sell_order_id = order_id
        # 完成一个网格循环
        self.completed_grids += 1
        profit = self.config.grid_step * (self.config.order_usdt / self.levels[level_idx].price)
        self.total_profit += profit

    def status(self) -> str:
        """返回网格状态摘要。"""
        bought = sum(1 for l in self.levels if l.buy_filled and not l.sell_filled)
        available = sum(1 for l in self.levels if not l.buy_filled)
        lines = [
            f"📊 网格状态: {self.config.symbol}",
            f"区间: {self.config.lower_price:.2f} - {self.config.upper_price:.2f}",
            f"网格数: {self.config.grid_count}",
            f"每格: {self.config.order_usdt:.0f} USDT",
            f"",
            f"已买入待卖: {bought} 格",
            f"可用买入:   {available} 格",
            f"已完成循环: {self.completed_grids} 次",
            f"累计利润:   {self.total_profit:.2f} USDT",
        ]
        return "\n".join(lines)
