from okx_paper_bot.experiments import ExperimentService, ExperimentSpec, expand_param_grid
from okx_paper_bot.market import MarketDataService


def test_expand_param_grid_merges_fixed_params():
    params = expand_param_grid({"slow": 20}, {"fast": [3, 5]})

    assert params == [{"slow": 20, "fast": 3}, {"slow": 20, "fast": 5}]


def test_experiment_service_persists_multiple_runs(tmp_path):
    database = __import__("tests.conftest", fromlist=["make_database"]).make_database(tmp_path)
    market = MarketDataService()

    with database.session() as session:
        market.seed_sample(session, count=100)
        experiment, runs = ExperimentService(market).create_and_run(
            session,
            ExperimentSpec(
                name="grid",
                strategy_key="ma_crossover",
                fixed_params={"slow": 12},
                param_grid={"fast": [3, 5]},
            ),
        )

    assert experiment.id is not None
    assert len(runs) == 2
    assert all(run.experiment_id == experiment.id for run in runs)
