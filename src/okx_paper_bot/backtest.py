from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BacktestTrade:
    """回测中的一笔交易记录。"""
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    amount: float = 0.0
    side: str = "buy"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # signal / stop_loss / take_profit / trailing_stop


@dataclass
class BacktestResult:
    """回测结果汇总。"""
    symbol: str
    timeframe: str
    start_time: str
    end_time: str
    initial_balance: float
    final_balance: float
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def total_return(self) -> float:
        return (self.final_balance - self.initial_balance) / self.initial_balance

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        return sum(losses) / len(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def max_drawdown(self) -> float:
        """最大回撤（百分比）。"""
        if not self.trades:
            return 0.0
        equity = [self.initial_balance]
        for t in self.trades:
            equity.append(equity[-1] + t.pnl)
        peak = equity[0]
        max_dd = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def summary(self) -> str:
        lines = [
            f"📊 回测结果: {self.symbol} ({self.timeframe})",
            f"时间段: {self.start_time} → {self.end_time}",
            f"",
            f"初始资金: {self.initial_balance:.2f} USDT",
            f"最终资金: {self.final_balance:.2f} USDT",
            f"总收益: {self.total_return*100:+.2f}%",
            f"",
            f"总交易数: {self.total_trades}",
            f"盈利: {self.winning_trades} | 亏损: {self.losing_trades}",
            f"胜率: {self.win_rate*100:.1f}%",
            f"平均盈利: {self.avg_win:+.2f} USDT",
            f"平均亏损: {self.avg_loss:+.2f} USDT",
            f"盈亏比: {self.profit_factor:.2f}",
            f"最大回撤: {self.max_drawdown*100:.2f}%",
        ]
        return "\n".join(lines)
