from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class BotConfig:
    symbol: str = "BTC/USDT"
    symbols: tuple[str, ...] = ()  # 多交易对，空则用 symbol
    timeframe: str = "1m"
    okx_demo: bool = True
    strategy_name: str = "ma_crossover"  # ma_crossover / rsi / bollinger
    fast_window: int = 5
    slow_window: int = 20
    rsi_period: int = 14
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    initial_balance_usdt: float = 1_000.0
    order_usdt: float = 100.0
    max_position_fraction: float = 0.25
    fee_pct: float = 0.001        # 0.1% 手续费
    slippage_pct: float = 0.0005  # 0.05% 滑点
    db_path: Path = Path("data/trades.sqlite3")
    api_key: str | None = None
    secret: str | None = None
    password: str | None = None
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.0
    notify_file: Path = Path("data/notifications.log")
    loop_interval_seconds: int = 60

    @property
    def all_symbols(self) -> list[str]:
        if self.symbols:
            return list(self.symbols)
        return [self.symbol]

    @classmethod
    def from_env(cls) -> "BotConfig":
        load_dotenv()
        raw_symbols = os.getenv("OKX_SYMBOLS", "")
        symbols = tuple(s.strip() for s in raw_symbols.split(",") if s.strip()) if raw_symbols else ()
        return cls(
            symbol=os.getenv("OKX_SYMBOL", cls.symbol),
            symbols=symbols,
            timeframe=os.getenv("OKX_TIMEFRAME", cls.timeframe),
            okx_demo=_parse_bool(os.getenv("OKX_DEMO"), default=True),
            strategy_name=os.getenv("STRATEGY", cls.strategy_name),
            fast_window=int(os.getenv("FAST_WINDOW", cls.fast_window)),
            slow_window=int(os.getenv("SLOW_WINDOW", cls.slow_window)),
            rsi_period=int(os.getenv("RSI_PERIOD", cls.rsi_period)),
            rsi_buy=float(os.getenv("RSI_BUY", cls.rsi_buy)),
            rsi_sell=float(os.getenv("RSI_SELL", cls.rsi_sell)),
            bollinger_period=int(os.getenv("BOLLINGER_PERIOD", cls.bollinger_period)),
            bollinger_std=float(os.getenv("BOLLINGER_STD", cls.bollinger_std)),
            initial_balance_usdt=float(os.getenv("INITIAL_BALANCE_USDT", cls.initial_balance_usdt)),
            order_usdt=float(os.getenv("ORDER_USDT", cls.order_usdt)),
            max_position_fraction=float(os.getenv("MAX_POSITION_FRACTION", cls.max_position_fraction)),
            fee_pct=float(os.getenv("FEE_PCT", cls.fee_pct)),
            slippage_pct=float(os.getenv("SLIPPAGE_PCT", cls.slippage_pct)),
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
