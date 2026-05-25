from datetime import datetime, timedelta, timezone

from okx_paper_bot.market import CandleData
from okx_paper_bot.strategies import create_strategy, strategy_templates


def _candles(values):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        CandleData(start + timedelta(minutes=i), value, value, value, value)
        for i, value in enumerate(values)
    ]


def test_strategy_templates_include_required_presets():
    keys = {item["key"] for item in strategy_templates()}

    assert {"ma_crossover", "rsi", "macd", "bollinger", "breakout", "grid"} <= keys


def test_ma_crossover_emits_buy_intent_after_cross():
    strategy = create_strategy("ma_crossover", {"fast": 2, "slow": 3})
    values = [10, 9, 8, 9, 11]

    assert strategy.signal(_candles(values)) == "buy"
