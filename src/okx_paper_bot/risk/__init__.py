"""Risk and live-trading safety checks."""
from __future__ import annotations

from dataclasses import dataclass

from okx_paper_bot.config import AppSettings


@dataclass(frozen=True)
class LiveTradeRequest:
    broker_mode: str
    instance_allow_live: bool
    confirmation: str | None


@dataclass(frozen=True)
class LiveSafetyResult:
    allowed: bool
    reasons: list[str]


class LiveSafetyGate:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    def validate(self, request: LiveTradeRequest) -> LiveSafetyResult:
        reasons: list[str] = []
        if request.broker_mode != "okx_live":
            return LiveSafetyResult(True, [])
        if not self.settings.allow_live_trading:
            reasons.append("environment ALLOW_LIVE_TRADING is disabled")
        if not request.instance_allow_live:
            reasons.append("strategy instance allow_live is disabled")
        if request.confirmation != self.settings.live_confirm_phrase:
            reasons.append("live confirmation phrase mismatch")
        return LiveSafetyResult(not reasons, reasons)


def size_by_quote(cash: float, price: float, quote_amount: float) -> float:
    if cash <= 0 or price <= 0 or quote_amount <= 0:
        return 0.0
    return min(cash, quote_amount) / price
