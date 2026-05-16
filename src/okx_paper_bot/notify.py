from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


BJT = timezone(timedelta(hours=8))


def _now_bjt() -> str:
    return datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S")


def format_trade_signal(
    symbol: str,
    signal: str,
    price: float,
    amount: float,
    order_status: str,
    balance: float,
    positions: dict,
    reason: str = "",
) -> str:
    """格式化交易信号通知消息。"""
    emoji = {"buy": "🟢", "sell": "🔴", "stop_loss": "🛑", "take_profit": "🎯", "trailing_stop": "📉"}.get(signal, "📊")
    lines = [
        f"{emoji} {signal.upper()} {symbol}",
        f"时间: {_now_bjt()}",
        f"价格: {price:.2f} USDT",
        f"数量: {amount:.8f}",
        f"状态: {order_status}",
    ]
    if reason:
        lines.append(f"原因: {reason}")
    lines.append(f"余额: {balance:.2f} USDT")
    if positions:
        for sym, qty in positions.items():
            lines.append(f"持仓: {sym} = {qty:.8f}")
    return "\n".join(lines)


def format_error(symbol: str, error: str) -> str:
    return f"⚠️ ERROR {symbol}\n时间: {_now_bjt()}\n{error}"


def format_status(symbol: str, price: float, balance: float, positions: dict, signal: str) -> str:
    pos_str = ", ".join(f"{s}={q:.6f}" for s, q in positions.items()) or "空仓"
    return f"📊 {symbol} = {price:.2f} | {signal.upper()} | 余额 {balance:.2f} | {pos_str}"


def notify(message: str, notify_file: Path | str | None = None) -> None:
    """写入通知到文件（可被外部工具读取转发）。"""
    if notify_file:
        path = Path(notify_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(message + "\n---\n")
    # 始终打印到 stdout
    print(message)
    print("---")
