import pytest

from app.algorithms.backtest import backtest
from app.algorithms.demand import ConsumptionPattern
from app.algorithms.model_pool import ModelPool


def test_model_pool_routes_by_consumption_pattern() -> None:
    pool = ModelPool()
    assert pool.select(ConsumptionPattern.STABLE).name == "AutoARIMA"
    assert pool.select(ConsumptionPattern.INTERMITTENT).name == "Croston"
    assert pool.select(ConsumptionPattern.SPARE_PART).name == "SBA"


def test_backtest_report_contains_mape_and_wape() -> None:
    report = backtest([10, 11, 9, 12, 10, 13])
    assert report.sample_count == 2
    assert 0 <= report.mape
    assert 0 <= report.wape


def test_backtest_rejects_short_series() -> None:
    with pytest.raises(ValueError):
        backtest([1, 2], holdout=2)
