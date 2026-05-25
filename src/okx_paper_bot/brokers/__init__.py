"""Broker adapters for paper, OKX demo, and OKX live."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode

import requests

from okx_paper_bot.config import AppSettings
from okx_paper_bot.market import CandleData, ensure_utc, timeframe_seconds
from okx_paper_bot.risk import LiveSafetyGate, LiveTradeRequest, size_by_quote


BROKER_MODES = {"paper", "okx_demo", "okx_live"}
MARKET_TYPES = {"spot", "swap"}


@dataclass
class Fill:
    side: str
    amount: float
    price: float
    fee: float
    pnl: float = 0.0
    order_type: str = "market"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaperAccount:
    cash: float
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_size: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    fee_paid: float = 0.0
    fills: list[Fill] = field(default_factory=list)

    def equity(self, price: float) -> float:
        return self.cash + self.position_size * price

    def buy(self, *, price: float, quote_amount: float, order_type: str = "market") -> Fill | None:
        exec_price = price * (1 + self.slippage_rate)
        amount = size_by_quote(self.cash, exec_price, quote_amount)
        if amount <= 0:
            return None
        notional = amount * exec_price
        fee = notional * self.fee_rate
        if notional + fee > self.cash:
            amount = self.cash / (exec_price * (1 + self.fee_rate))
            notional = amount * exec_price
            fee = notional * self.fee_rate
        previous_cost = self.avg_entry_price * self.position_size
        self.cash -= notional + fee
        self.position_size += amount
        self.avg_entry_price = (previous_cost + notional) / self.position_size
        self.fee_paid += fee
        fill = Fill("buy", amount, exec_price, fee, order_type=order_type)
        self.fills.append(fill)
        return fill

    def sell(self, *, price: float, amount: float, order_type: str = "market") -> Fill | None:
        amount = min(amount, self.position_size)
        if amount <= 1e-12:
            return None
        exec_price = price * (1 - self.slippage_rate)
        notional = amount * exec_price
        fee = notional * self.fee_rate
        pnl = (exec_price - self.avg_entry_price) * amount - fee
        self.cash += notional - fee
        self.position_size -= amount
        if self.position_size <= 1e-12:
            self.position_size = 0.0
            self.avg_entry_price = 0.0
        self.realized_pnl += pnl
        self.fee_paid += fee
        fill = Fill("sell", amount, exec_price, fee, pnl=pnl, order_type=order_type)
        self.fills.append(fill)
        return fill


def okx_headers_for_mode(broker_mode: str) -> dict[str, str]:
    if broker_mode == "okx_demo":
        return {"x-simulated-trading": "1"}
    return {}


def default_td_mode(market_type: str) -> str:
    if market_type == "spot":
        return "cash"
    if market_type == "swap":
        return "cross"
    raise ValueError(f"unsupported market_type: {market_type}")


def okx_inst_id(symbol: str, market_type: str) -> str:
    normalized = symbol.split(":", 1)[0].replace("/", "-").upper()
    if market_type == "swap" and not normalized.endswith("-SWAP"):
        parts = normalized.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}-SWAP"
    return normalized


def build_okx_order_params(
    *,
    market_type: str,
    inst_id: str,
    side: str,
    amount: float,
    order_type: str = "market",
    price: float | None = None,
    td_mode: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "instId": inst_id,
        "tdMode": td_mode or default_td_mode(market_type),
        "side": side,
        "ordType": "market" if order_type == "market" else "limit",
        "sz": str(amount),
    }
    if params["ordType"] == "limit":
        if price is None or price <= 0:
            raise ValueError("limit order price is required")
        params["px"] = str(price)
    if market_type == "spot" and params["ordType"] == "market" and side == "buy":
        params["tgtCcy"] = "base_ccy"
    return params


class OKXGateway:
    def __init__(self, settings: AppSettings, broker_mode: str, market_type: str):
        if broker_mode not in {"okx_demo", "okx_live"}:
            raise ValueError("OKXGateway only supports okx_demo or okx_live")
        if market_type not in MARKET_TYPES:
            raise ValueError(f"unsupported market_type: {market_type}")
        self.settings = settings
        self.broker_mode = broker_mode
        self.market_type = market_type

    def create_ccxt_client(self, *, authenticated: bool = True, ccxt_module: Any | None = "auto"):
        if ccxt_module == "auto":
            import ccxt as ccxt_module  # type: ignore[no-redef]

        params: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "swap" if self.market_type == "swap" else "spot"},
            "headers": okx_headers_for_mode(self.broker_mode),
        }
        if self.broker_mode == "okx_demo":
            params["sandbox"] = True
        if authenticated:
            params["apiKey"] = self.settings.okx_api_key
            params["secret"] = self.settings.okx_api_secret
            params["password"] = self.settings.okx_api_password
        return ccxt_module.okx(params)

    def request_private(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.okx_api_key or not self.settings.okx_api_secret or not self.settings.okx_api_password:
            raise PermissionError("OKX API credentials are not configured")

        payload = "" if body is None else json.dumps(body, separators=(",", ":"))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        message = timestamp + method.upper() + path + payload
        signature = base64.b64encode(
            hmac.new(self.settings.okx_api_secret.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": self.settings.okx_api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.settings.okx_api_password,
            **okx_headers_for_mode(self.broker_mode),
        }
        response = requests.request(
            method.upper(),
            f"https://www.okx.com{path}",
            headers=headers,
            data=payload or None,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def fetch_account_balance(self, ccy: str | None = None) -> dict[str, Any]:
        path = "/api/v5/account/balance"
        if ccy:
            path = f"{path}?ccy={ccy}"
        return self.request_private("GET", path)

    def fetch_positions(self) -> dict[str, Any]:
        return self.request_private("GET", "/api/v5/account/positions")

    def fetch_order_details(self, *, inst_id: str, order_id: str) -> dict[str, Any]:
        query = urlencode({"instId": inst_id, "ordId": order_id})
        return self.request_private("GET", f"/api/v5/trade/order?{query}")

    def fetch_ticker(self, *, symbol: str, ccxt_module: Any | None = "auto") -> dict[str, Any]:
        client = self.create_ccxt_client(authenticated=False, ccxt_module=ccxt_module)
        return client.fetch_ticker(symbol)

    def adjust_demo_balance(self, *, adjustment_type: str, adjustments: list[dict[str, str]]) -> dict[str, Any]:
        if self.broker_mode != "okx_demo":
            raise ValueError("demo balance adjustment is only available for OKX Demo")
        return self.request_private(
            "POST",
            "/api/v5/account/demo-adjust-balance",
            {"type": adjustment_type, "adjustments": adjustments},
        )

    def fetch_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        since: datetime | None = None,
        ccxt_module: Any | None = "auto",
    ) -> list[CandleData]:
        client = self.create_ccxt_client(authenticated=False, ccxt_module=ccxt_module)
        if since is None:
            rows = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        else:
            rows = client.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=int(ensure_utc(since).timestamp() * 1000),
                limit=limit,
            )
        frame_ms = timeframe_seconds(timeframe) * 1000
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        candles: list[CandleData] = []
        for row in rows:
            ts_ms, open_, high, low, close, volume = row[:6]
            candles.append(
                CandleData(
                    ts=datetime.fromtimestamp(float(ts_ms) / 1000, tz=timezone.utc),
                    open=float(open_),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume),
                    completed=(float(ts_ms) + frame_ms) <= now_ms,
                )
            )
        return candles

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: float | None = None,
        td_mode: str | None = None,
        instance_allow_live: bool = False,
        confirmation: str | None = None,
        ccxt_module: Any | None = "auto",
    ):
        safety = LiveSafetyGate(self.settings).validate(
            LiveTradeRequest(
                broker_mode=self.broker_mode,
                instance_allow_live=instance_allow_live,
                confirmation=confirmation,
            )
        )
        if not safety.allowed:
            raise PermissionError("; ".join(safety.reasons))
        client = self.create_ccxt_client(authenticated=True, ccxt_module=ccxt_module)
        params = {"tdMode": td_mode or default_td_mode(self.market_type)}
        return client.create_order(symbol, order_type, side, amount, price, params)
