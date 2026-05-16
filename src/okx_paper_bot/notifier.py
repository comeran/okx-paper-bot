from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TradeEvent:
    """交易事件，用于通知。"""
    symbol: str
    side: str  # buy / sell / stop_loss / take_profit / trailing_stop
    amount: float
    price: float
    signal: str = ""
    reason: str = ""
    balance_usdt: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)

    def format_message(self) -> str:
        emoji = {"buy": "🟢", "sell": "🔴", "stop_loss": "🛑", "take_profit": "🎯", "trailing_stop": "📉"}.get(self.side, "📊")
        lines = [
            f"{emoji} **{self.side.upper()}** {self.symbol}",
            f"价格: {self.price:.2f} USDT",
            f"数量: {self.amount:.6f}",
        ]
        if self.reason:
            lines.append(f"原因: {self.reason}")
        lines.append(f"余额: {self.balance_usdt:.2f} USDT")
        if self.positions:
            pos_str = ", ".join(f"{k}: {v:.6f}" for k, v in self.positions.items())
            lines.append(f"持仓: {pos_str}")
        return "\n".join(lines)


# 通知回调类型: 接收 TradeEvent，无返回值
NotifyCallback = Callable[[TradeEvent], None]


def console_notifier(event: TradeEvent) -> None:
    """打印到控制台。"""
    print(event.format_message())
    print("---")


def hermes_notifier(event: TradeEvent) -> None:
    """通过 hermes CLI 发送通知到微信。"""
    try:
        msg = event.format_message()
        subprocess.run(
            ["hermes", "send", "--platform", "weixin", "--message", msg],
            capture_output=True, timeout=10,
        )
    except Exception as exc:
        print(f"[通知发送失败] {exc}")


def make_composite_notifier(*notifiers: NotifyCallback) -> NotifyCallback:
    """组合多个通知器，依次调用。"""
    def _notify(event: TradeEvent) -> None:
        for n in notifiers:
            try:
                n(event)
            except Exception:
                pass
    return _notify
