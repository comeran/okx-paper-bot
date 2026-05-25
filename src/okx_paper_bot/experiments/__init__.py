"""Experiment orchestration for parameter sweeps and backtest comparison."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import product
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from okx_paper_bot.backtest import EventBacktester, persist_backtest_result
from okx_paper_bot.market import MarketDataService
from okx_paper_bot.persistence.models import BacktestRun, Experiment


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    strategy_key: str
    strategy_instance_id: int | None = None
    market_type: str = "spot"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    initial_equity: float = 10000.0
    order_usdt: float = 500.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    fixed_params: dict[str, Any] = field(default_factory=dict)
    param_grid: dict[str, list[Any]] = field(default_factory=dict)
    description: str = ""
    data_source: str = "cached"
    candles_limit: int | None = 300
    start_date: date | None = None
    end_date: date | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    requested_start_ts: datetime | None = None
    requested_end_ts: datetime | None = None
    expected_candles: int | None = None
    fetch_batches: int | None = None
    fetch_batch_size: int | None = None


class ExperimentService:
    def __init__(self, market_data: MarketDataService | None = None, backtester: EventBacktester | None = None):
        self.market_data = market_data or MarketDataService()
        self.backtester = backtester or EventBacktester()

    def create_and_run(self, session: Session, spec: ExperimentSpec) -> tuple[Experiment, list[BacktestRun]]:
        if spec.start_ts and spec.end_ts:
            candles = self.market_data.list_candles(
                session,
                market_type=spec.market_type,
                symbol=spec.symbol,
                timeframe=spec.timeframe,
                start=spec.start_ts,
                end=spec.end_ts,
                completed_only=True,
            )
        else:
            candles = self.market_data.list_candles(
                session,
                market_type=spec.market_type,
                symbol=spec.symbol,
                timeframe=spec.timeframe,
                limit=spec.candles_limit,
                completed_only=True,
                latest=True,
            )
        if len(candles) < 3:
            raise ValueError(
                f"not enough completed candles for {spec.market_type} {spec.symbol} {spec.timeframe}; "
                "automatic data preparation did not return enough data"
            )
        request = {
            "strategy_key": spec.strategy_key,
            "strategy_instance_id": spec.strategy_instance_id,
            "market_type": spec.market_type,
            "symbol": spec.symbol,
            "timeframe": spec.timeframe,
            "initial_equity": spec.initial_equity,
            "order_usdt": spec.order_usdt,
            "fee_rate": spec.fee_rate,
            "slippage_rate": spec.slippage_rate,
            "fixed_params": spec.fixed_params,
            "param_grid": spec.param_grid,
            "data_source": spec.data_source,
            "candles_count": len(candles),
            "start_ts": candles[0].ts.isoformat(),
            "end_ts": candles[-1].ts.isoformat(),
        }
        if spec.candles_limit is not None:
            request["candles_limit"] = spec.candles_limit
        for key in ("start_date", "end_date", "requested_start_ts", "requested_end_ts"):
            value = getattr(spec, key)
            if value is not None:
                request[key] = value.isoformat()
        if spec.expected_candles is not None:
            request["expected_candles"] = spec.expected_candles
        if spec.fetch_batches is not None:
            request["fetch_batches"] = spec.fetch_batches
        if spec.fetch_batch_size is not None:
            request["fetch_batch_size"] = spec.fetch_batch_size

        experiment = Experiment(
            name=spec.name,
            description=spec.description,
            request=request,
        )
        session.add(experiment)
        session.flush()

        runs: list[BacktestRun] = []
        for params in expand_param_grid(spec.fixed_params, spec.param_grid):
            result = self.backtester.run(
                strategy_key=spec.strategy_key,
                strategy_params=params,
                candles=candles,
                market_type=spec.market_type,
                symbol=spec.symbol,
                timeframe=spec.timeframe,
                initial_equity=spec.initial_equity,
                order_usdt=spec.order_usdt,
                fee_rate=spec.fee_rate,
                slippage_rate=spec.slippage_rate,
            )
            runs.append(persist_backtest_result(session, result, experiment_id=experiment.id))
        return experiment, runs

    def leaderboard(self, session: Session, experiment_id: int | None = None, limit: int = 50) -> list[BacktestRun]:
        stmt = select(BacktestRun).order_by(
            BacktestRun.total_return_pct.desc(),
            BacktestRun.max_drawdown_pct.desc(),
            BacktestRun.sharpe.desc(),
        )
        if experiment_id is not None:
            stmt = stmt.where(BacktestRun.experiment_id == experiment_id)
        return list(session.scalars(stmt.limit(limit)).all())


def expand_param_grid(fixed: dict[str, Any], grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [dict(fixed)]
    keys = list(grid.keys())
    values = [items if isinstance(items, list) else [items] for items in grid.values()]
    combos = []
    for raw in product(*values):
        params = dict(fixed)
        params.update(dict(zip(keys, raw)))
        combos.append(params)
    return combos
