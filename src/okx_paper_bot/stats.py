"""收益统计模块 - 实时持仓盈亏、收益率、夏普比率。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJT = timezone(timedelta(hours=8))


@dataclass
class EquitySnapshot:
    """权益快照。"""
    timestamp: str
    balance_usdt: float
    positions_value: float  # 持仓市值
    total_equity: float     # 总权益 = balance + positions_value
    pnl: float = 0.0        # 相对初始资金的盈亏
    pnl_pct: float = 0.0    # 盈亏百分比


@dataclass
class PortfolioStats:
    """投资组合统计。"""
    initial_balance: float
    current_balance: float
    positions: dict[str, float]  # symbol -> amount
    current_prices: dict[str, float]  # symbol -> price
    trades: list[dict] = field(default_factory=list)

    @property
    def positions_value(self) -> float:
        """持仓总市值。"""
        total = 0.0
        for sym, qty in self.positions.items():
            price = self.current_prices.get(sym, 0)
            total += qty * price
        return total

    @property
    def total_equity(self) -> float:
        """总权益。"""
        return self.current_balance + self.positions_value

    @property
    def total_pnl(self) -> float:
        """总盈亏。"""
        return self.total_equity - self.initial_balance

    @property
    def total_return(self) -> float:
        """总收益率。"""
        return self.total_pnl / self.initial_balance if self.initial_balance > 0 else 0

    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏（持仓浮盈浮亏）。"""
        # 需要知道入场价才能算，这里简化为 0
        return 0.0

    @property
    def realized_pnl(self) -> float:
        """已实现盈亏（已完成交易）。"""
        return sum(t.get("pnl", 0) for t in self.trades)

    def snapshot(self) -> EquitySnapshot:
        """生成当前权益快照。"""
        return EquitySnapshot(
            timestamp=datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S"),
            balance_usdt=self.current_balance,
            positions_value=self.positions_value,
            total_equity=self.total_equity,
            pnl=self.total_pnl,
            pnl_pct=self.total_return,
        )

    def format_report(self) -> str:
        """格式化收益报告。"""
        lines = [
            f"📊 收益报告",
            f"时间: {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"初始资金: {self.initial_balance:.2f} USDT",
            f"可用余额: {self.current_balance:.2f} USDT",
            f"持仓市值: {self.positions_value:.2f} USDT",
            f"总权益:   {self.total_equity:.2f} USDT",
            f"",
            f"总盈亏: {self.total_pnl:+.2f} USDT ({self.total_return*100:+.2f}%)",
        ]
        if self.positions:
            lines.append(f"")
            lines.append(f"持仓明细:")
            for sym, qty in self.positions.items():
                price = self.current_prices.get(sym, 0)
                value = qty * price
                lines.append(f"  {sym}: {qty:.8f} × {price:.2f} = {value:.2f} USDT")
        if self.trades:
            wins = sum(1 for t in self.trades if t.get("pnl", 0) > 0)
            losses = sum(1 for t in self.trades if t.get("pnl", 0) <= 0)
            lines.append(f"")
            lines.append(f"交易统计:")
            lines.append(f"  总交易: {len(self.trades)} | 盈利: {wins} | 亏损: {losses}")
            if len(self.trades) > 0:
                lines.append(f"  胜率: {wins/len(self.trades)*100:.1f}%")
        return "\n".join(lines)


class EquityTracker:
    """权益追踪器 - 记录权益变化历史，计算夏普比率等。"""

    def __init__(self, history_file: Path | str | None = None):
        self.history: list[EquitySnapshot] = []
        self.history_file = Path(history_file) if history_file else None
        if self.history_file and self.history_file.exists():
            self._load()

    def _load(self) -> None:
        """从文件加载历史数据。"""
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
            for item in data:
                self.history.append(EquitySnapshot(**item))
        except Exception:
            pass

    def _save(self) -> None:
        """保存历史到文件。"""
        if not self.history_file:
            return
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "timestamp": s.timestamp,
                "balance_usdt": s.balance_usdt,
                "positions_value": s.positions_value,
                "total_equity": s.total_equity,
                "pnl": s.pnl,
                "pnl_pct": s.pnl_pct,
            }
            for s in self.history
        ]
        with open(self.history_file, "w") as f:
            json.dump(data, f, indent=2)

    def record(self, snapshot: EquitySnapshot) -> None:
        """记录一个权益快照。"""
        self.history.append(snapshot)
        self._save()

    def returns(self) -> list[float]:
        """计算每期收益率序列。"""
        if len(self.history) < 2:
            return []
        rets = []
        for i in range(1, len(self.history)):
            prev = self.history[i - 1].total_equity
            curr = self.history[i].total_equity
            if prev > 0:
                rets.append((curr - prev) / prev)
        return rets

    def sharpe_ratio(self, risk_free_rate: float = 0.0, periods_per_year: int = 365) -> float:
        """计算年化夏普比率。

        Args:
            risk_free_rate: 无风险利率（年化），默认 0
            periods_per_year: 每年周期数（日=365, 小时=8760）
        """
        rets = self.returns()
        if len(rets) < 2:
            return 0.0
        mean_ret = sum(rets) / len(rets)
        var = sum((r - mean_ret) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var) if var > 0 else 0
        if std == 0:
            return 0.0
        rf_per_period = risk_free_rate / periods_per_year
        return (mean_ret - rf_per_period) / std * math.sqrt(periods_per_year)

    def max_drawdown(self) -> float:
        """最大回撤。"""
        if not self.history:
            return 0.0
        equities = [s.total_equity for s in self.history]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd
