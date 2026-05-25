"""Market data types and SQLite-backed candle cache."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from okx_paper_bot.persistence.models import Candle


@dataclass(frozen=True)
class CandleData:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    completed: bool = True


TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return TIMEFRAME_SECONDS[timeframe]


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MarketDataService:
    def upsert_candles(
        self,
        session: Session,
        *,
        market_type: str,
        symbol: str,
        timeframe: str,
        candles: Iterable[CandleData],
        source: str = "manual",
    ) -> int:
        items = list(candles)
        if not items:
            return 0

        timestamps = [ensure_utc(c.ts) for c in items]
        existing_rows = session.scalars(
            select(Candle).where(
                Candle.market_type == market_type,
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.ts.in_(timestamps),
            )
        ).all()
        existing_map = {ensure_utc(row.ts): row for row in existing_rows}

        count = 0
        for item in items:
            ts = ensure_utc(item.ts)
            existing = existing_map.get(ts)
            if existing:
                existing.open = item.open
                existing.high = item.high
                existing.low = item.low
                existing.close = item.close
                existing.volume = item.volume
                existing.completed = item.completed
                existing.source = source
            else:
                existing = Candle(
                    market_type=market_type,
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=ts,
                    open=item.open,
                    high=item.high,
                    low=item.low,
                    close=item.close,
                    volume=item.volume,
                    completed=item.completed,
                    source=source,
                )
                session.add(existing)
                existing_map[ts] = existing
            count += 1
        session.flush()
        return count

    def list_candles(
        self,
        session: Session,
        *,
        market_type: str,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        completed_only: bool = True,
        latest: bool = False,
    ) -> list[CandleData]:
        stmt = select(Candle).where(
            Candle.market_type == market_type,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        if start is not None:
            stmt = stmt.where(Candle.ts >= ensure_utc(start))
        if end is not None:
            stmt = stmt.where(Candle.ts <= ensure_utc(end))
        if completed_only:
            stmt = stmt.where(Candle.completed.is_(True))
        stmt = stmt.order_by(Candle.ts.desc() if latest and limit else Candle.ts.asc())
        if limit:
            stmt = stmt.limit(limit)
        rows = session.scalars(stmt).all()
        if latest and limit:
            rows = list(reversed(rows))
        return [
            CandleData(
                ts=ensure_utc(row.ts),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                completed=row.completed,
            )
            for row in rows
        ]

    def seed_sample(
        self,
        session: Session,
        *,
        market_type: str = "spot",
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        count: int = 360,
    ) -> int:
        seconds = timeframe_seconds(timeframe)
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(
            seconds=seconds * count
        )
        _SEED_PRICES = {
            "BTC": 62000.0, "ETH": 2500.0, "SOL": 150.0, "BNB": 580.0,
            "XRP": 0.55, "ADA": 0.45, "DOGE": 0.12, "AVAX": 35.0,
        }
        base = symbol.split("/")[0].upper()
        price = next((p for prefix, p in _SEED_PRICES.items() if base.startswith(prefix)), 10.0)
        candles: list[CandleData] = []
        for i in range(count):
            ts = start + timedelta(seconds=seconds * i)
            drift = i * 6.5
            wave = math.sin(i / 9) * 850 + math.sin(i / 29) * 2100
            close = max(10.0, price + drift + wave)
            open_ = candles[-1].close if candles else close * 0.998
            high = max(open_, close) * (1 + 0.0025 + abs(math.sin(i)) * 0.001)
            low = min(open_, close) * (1 - 0.0025 - abs(math.cos(i)) * 0.001)
            candles.append(CandleData(ts=ts, open=open_, high=high, low=low, close=close, volume=100 + i % 50))
        return self.upsert_candles(
            session, market_type=market_type, symbol=symbol, timeframe=timeframe, candles=candles, source="sample"
        )
