from __future__ import annotations

from dataclasses import dataclass, field
from time import sleep
from typing import Any, Callable, TypeVar

from okx_paper_bot.config import BotConfig

T = TypeVar("T")


@dataclass
class FakeExchange:
    options: dict[str, Any] = field(default_factory=lambda: {"defaultType": "spot"})
    headers: dict[str, str] = field(default_factory=dict)
    candles: list[list[float]] = field(default_factory=list)
    calls: list[tuple[str, str, int]] = field(default_factory=list)

    def fetch_ohlcv(self, symbol: str, timeframe: str, since=None, limit: int | None = None):
        limit = limit or len(self.candles)
        self.calls.append((symbol, timeframe, limit))
        return self.candles[-limit:]


def retry_call(fn: Callable[[], T], attempts: int = 3, delay_seconds: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - exchange libraries raise broad transient errors
            last_error = exc
            if attempt < attempts - 1 and delay_seconds > 0:
                sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def create_okx_exchange(
    config: BotConfig,
    ccxt_module: Any | None = "auto",
    *,
    auth: bool = True,
):
    """Create an OKX exchange client.

    Public market-data calls should use ``auth=False`` so a bad API passphrase
    does not break candles, charts, or backtests.
    """
    if ccxt_module == "auto":
        try:
            import ccxt as ccxt_module  # type: ignore[no-redef]
        except ModuleNotFoundError:
            ccxt_module = None

    if ccxt_module is None:
        exchange = FakeExchange()
    else:
        params: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
            "headers": {},
        }
        if auth:
            if config.api_key:
                params["apiKey"] = config.api_key
            if config.secret:
                params["secret"] = config.secret
            if config.password:
                params["password"] = config.password
        exchange = ccxt_module.okx(params)

    if config.okx_demo:
        exchange.headers["x-simulated-trading"] = "1"
    return exchange


def create_okx_market_data_exchange(config: BotConfig, ccxt_module: Any | None = "auto"):
    """Create an unauthenticated OKX client for public candles/tickers."""
    return create_okx_exchange(config, ccxt_module=ccxt_module, auth=False)


def fetch_close_prices(
    exchange: Any,
    symbol: str,
    timeframe: str,
    limit: int,
    attempts: int = 3,
    delay_seconds: float = 1.0,
) -> list[float]:
    candles = retry_call(
        lambda: exchange.fetch_ohlcv(symbol, timeframe, limit=limit),
        attempts=attempts,
        delay_seconds=delay_seconds,
    )
    if not candles:
        raise ValueError(f"no OHLCV candles returned for {symbol} {timeframe}")
    return [float(candle[4]) for candle in candles]
