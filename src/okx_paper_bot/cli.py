"""Command line entrypoint for the rebuilt OKX quant workbench."""
from __future__ import annotations

import argparse
import json

import uvicorn

from okx_paper_bot.api import create_app
from okx_paper_bot.config import AppSettings
from okx_paper_bot.experiments import ExperimentService, ExperimentSpec
from okx_paper_bot.market import MarketDataService
from okx_paper_bot.persistence.db import create_database


def main() -> None:
    parser = argparse.ArgumentParser(prog="okx-paper-bot")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="Create database schema and seed strategy templates")

    seed = sub.add_parser("seed-sample", help="Seed deterministic sample candles")
    seed.add_argument("--market-type", default="spot")
    seed.add_argument("--symbol", default="BTC/USDT")
    seed.add_argument("--timeframe", default="1h")
    seed.add_argument("--count", type=int, default=360)

    backtest = sub.add_parser("backtest", help="Run a single backtest")
    backtest.add_argument("--strategy", default="ma_crossover")
    backtest.add_argument("--params", default='{"fast":5,"slow":20}')
    backtest.add_argument("--market-type", default="spot")
    backtest.add_argument("--symbol", default="BTC/USDT")
    backtest.add_argument("--timeframe", default="1h")

    dash = sub.add_parser("dashboard", help="Run FastAPI dashboard")
    dash.add_argument("--host", default=None)
    dash.add_argument("--port", type=int, default=None)

    args = parser.parse_args()
    settings = AppSettings.from_env()
    database = create_database(settings)

    if args.command == "init-db":
        database.init_schema()
        print(f"initialized database: {settings.public_database_url}")
        return

    if args.command == "seed-sample":
        database.init_schema()
        with database.session() as session:
            count = MarketDataService().seed_sample(
                session,
                market_type=args.market_type,
                symbol=args.symbol,
                timeframe=args.timeframe,
                count=args.count,
            )
        print(json.dumps({"inserted": count}, ensure_ascii=False))
        return

    if args.command == "backtest":
        database.init_schema()
        params = json.loads(args.params)
        with database.session() as session:
            experiment, runs = ExperimentService().create_and_run(
                session,
                ExperimentSpec(
                    name="cli backtest",
                    strategy_key=args.strategy,
                    market_type=args.market_type,
                    symbol=args.symbol,
                    timeframe=args.timeframe,
                    fixed_params=params,
                ),
            )
            result = {
                "experiment_id": experiment.id,
                "run_id": runs[0].id,
                "total_return_pct": runs[0].total_return_pct,
                "max_drawdown_pct": runs[0].max_drawdown_pct,
                "sharpe": runs[0].sharpe,
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "dashboard":
        host = args.host or settings.dashboard_host
        port = args.port or settings.dashboard_port
        app = create_app(settings=settings, database=database)
        uvicorn.run(app, host=host, port=port)
        return

    parser.print_help()
