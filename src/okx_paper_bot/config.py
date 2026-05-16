from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class BotConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    okx_demo: bool = True
    fast_window: int = 5
    slow_window: int = 20
    initial_balance_usdt: float = 1_000.0
    order_usdt: float = 100.0
    max_position_fraction: float = 0.25
    db_path: Path = Path("data/trades.sqlite3")
    api_key: str | None = None
    secret: str | None = None
    password: str | None = None
    # 止损止盈
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.0
    # 通知
    notify_file: Path = Path("data/notifications.log")
    # 持续运行
    loop_interval_seconds: int = 60

    @classmethod
    def from_env(cls) -> "BotConfig":
        load_dotenv()
        return cls(
            symbol=os.getenv("OKX_SYMBOL", cls.symbol),
            timeframe=os.getenv("OKX_TIMEFRAME", cls.timeframe),
            okx_demo=_parse_bool(os.getenv("OKX_DEMO"), default=True),
            fast_window=int(os.getenv("FAST_WINDOW", cls.fast_window)),
            slow_window=int(os.getenv("SLOW_WINDOW", cls.slow_window)),
            initial_balance_usdt=float(os.getenv("INITIAL_BALANCE_USDT", cls.initial_balance_usdt)),
            order_usdt=float(os.getenv("ORDER_USDT", cls.order_usdt)),
            max_position_fraction=float(os.getenv("MAX_POSITION_FRACTION", cls.max_position_fraction)),
            db_path=Path(os.getenv("DB_PATH", str(cls.db_path))),
            api_key=os.getenv("OKX_API_KEY"),
            secret=os.getenv("OKX_API_SECRET"),
            password=os.getenv("OKX_API_PASSWORD"),
            stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", cls.stop_loss_pct)),
            take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", cls.take_profit_pct)),
            trailing_stop_pct=float(os.getenv("TRAILING_STOP_PCT", cls.trailing_stop_pct)),
            notify_file=Path(os.getenv("NOTIFY_FILE", str(cls.notify_file))),
            loop_interval_seconds=int(os.getenv("LOOP_INTERVAL_SECONDS", cls.loop_interval_seconds)),
        )


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
