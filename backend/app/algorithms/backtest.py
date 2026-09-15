from dataclasses import dataclass
from typing import Iterable

from app.algorithms.demand import ConsumptionPattern, classify_consumption
from app.algorithms.metrics import mape, wape
from app.algorithms.model_pool import ModelPool


@dataclass(frozen=True)
class BacktestReport:
    model_name: str
    pattern: str
    mape: float
    wape: float
    sample_count: int


def backtest(values: Iterable[float], holdout: int = 2, pool: ModelPool | None = None) -> BacktestReport:
    series = [max(0.0, float(value)) for value in values]
    if len(series) <= holdout or holdout < 1:
        raise ValueError("series must be longer than holdout")
    train, actual = series[:-holdout], series[-holdout:]
    pattern = classify_consumption(train)
    output = (pool or ModelPool()).predict(train, holdout, pattern)
    return BacktestReport(output.model_name, pattern.value, mape(actual, output.values), wape(actual, output.values), holdout)

