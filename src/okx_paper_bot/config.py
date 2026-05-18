"""Bot configuration - all parameters from .env or CLI overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class StrategyInstance:
    """A single strategy instance with its own params and symbols."""
    name: str = "default"
    strategy: str = "ma_crossover"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "1h"
    fast_window: int = 5
    slow_window: int = 20
    rsi_period: int = 14
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.0
    tp1_pct: float = 0.0
    tp1_fraction: float = 0.5
    tp2_pct: float = 0.0
    tp2_fraction: float = 1.0
    order_usdt: float = 500.0

    def strategy_params(self) -> dict:
        """Return strategy-specific params for get_strategy()."""
        if self.strategy == "ma_crossover":
            return {"fast": self.fast_window, "slow": self.slow_window}
        elif self.strategy == "rsi":
            return {"period": self.rsi_period, "oversold": self.rsi_buy, "overbought": self.rsi_sell}
        elif self.strategy == "bollinger":
            return {"period": self.bollinger_period, "std_dev": self.bollinger_std}
        elif self.strategy == "macd":
            return {"fast_period": self.fast_window, "slow_period": self.slow_window, "signal_period": 9}
        return {}


STRATEGIES_FILE = "strategies.json"


def load_strategy_instances(config_dir: Path | str = Path(".")) -> list[StrategyInstance]:
    """Load strategy instances from strategies.json. Returns empty list if not found."""
    path = Path(config_dir) / STRATEGIES_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        instances = []
        for item in data.get("instances", []):
            instances.append(StrategyInstance(
                name=item.get("name", "default"),
                strategy=item.get("strategy", "ma_crossover"),
                symbols=item.get("symbols", ["BTC/USDT"]),
                timeframe=item.get("timeframe", "1h"),
                fast_window=int(item.get("fast_window", 5)),
                slow_window=int(item.get("slow_window", 20)),
                rsi_period=int(item.get("rsi_period", 14)),
                rsi_buy=float(item.get("rsi_buy", 30.0)),
                rsi_sell=float(item.get("rsi_sell", 70.0)),
                bollinger_period=int(item.get("bollinger_period", 20)),
                bollinger_std=float(item.get("bollinger_std", 2.0)),
                stop_loss_pct=float(item.get("stop_loss_pct", 0.05)),
                take_profit_pct=float(item.get("take_profit_pct", 0.10)),
                trailing_stop_pct=float(item.get("trailing_stop_pct", 0.0)),
                tp1_pct=float(item.get("tp1_pct", 0.0)),
                tp1_fraction=float(item.get("tp1_fraction", 0.5)),
                tp2_pct=float(item.get("tp2_pct", 0.0)),
                tp2_fraction=float(item.get("tp2_fraction", 1.0)),
                order_usdt=float(item.get("order_usdt", 500.0)),
            ))
        return instances
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def save_strategy_instances(instances: list[StrategyInstance], config_dir: Path | str = Path(".")) -> None:
    """Save strategy instances to strategies.json."""
    path = Path(config_dir) / STRATEGIES_FILE
    data = {"instances": []}
    for inst in instances:
        data["instances"].append({
            "name": inst.name,
            "strategy": inst.strategy,
            "symbols": inst.symbols,
            "timeframe": inst.timeframe,
            "fast_window": inst.fast_window,
            "slow_window": inst.slow_window,
            "rsi_period": inst.rsi_period,
            "rsi_buy": inst.rsi_buy,
            "rsi_sell": inst.rsi_sell,
            "bollinger_period": inst.bollinger_period,
            "bollinger_std": inst.bollinger_std,
            "stop_loss_pct": inst.stop_loss_pct,
            "take_profit_pct": inst.take_profit_pct,
            "trailing_stop_pct": inst.trailing_stop_pct,
            "tp1_pct": inst.tp1_pct,
            "tp1_fraction": inst.tp1_fraction,
            "tp2_pct": inst.tp2_pct,
            "tp2_fraction": inst.tp2_fraction,
            "order_usdt": inst.order_usdt,
        })
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class BotConfig:
    symbol: str = "BTC/USDT"
    symbols: tuple[str, ...] = ()
    timeframe: str = "1m"
    okx_demo: bool = True
    strategy_name: str = "ma_crossover"
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
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    db_path: Path = Path("data/trades.sqlite3")
    api_key: str | None = None
    secret: str | None = None
    password: str | None = None
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.0
    # 部分止盈
    tp1_pct: float = 0.0       # 第一档止盈触发点 (0.05 = 5%)
    tp1_fraction: float = 0.5  # 第一档平仓比例 (0.5 = 平一半)
    tp2_pct: float = 0.0       # 第二档止盈触发点
    tp2_fraction: float = 1.0  # 第二档平仓比例 (1.0 = 全平)
    notify_file: Path = Path("data/notifications.log")
    loop_interval_seconds: int = 60

    @property
    def all_symbols(self) -> list[str]:
        return list(self.symbols) if self.symbols else [self.symbol]

    @classmethod
    def from_env(cls) -> "BotConfig":
        load_dotenv()
        raw = os.getenv("OKX_SYMBOLS", "")
        symbols = tuple(s.strip() for s in raw.split(",") if s.strip()) if raw else ()
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
            tp1_pct=float(os.getenv("TP1_PCT", cls.tp1_pct)),
            tp1_fraction=float(os.getenv("TP1_FRACTION", cls.tp1_fraction)),
            tp2_pct=float(os.getenv("TP2_PCT", cls.tp2_pct)),
            tp2_fraction=float(os.getenv("TP2_FRACTION", cls.tp2_fraction)),
            notify_file=Path(os.getenv("NOTIFY_FILE", str(cls.notify_file))),
            loop_interval_seconds=int(os.getenv("LOOP_INTERVAL_SECONDS", cls.loop_interval_seconds)),
        )


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
