from dataclasses import dataclass
from enum import StrEnum
from statistics import mean, pstdev
from typing import Iterable


class ConsumptionPattern(StrEnum):
    STABLE = "stable"
    INTERMITTENT = "intermittent"
    SPARE_PART = "spare_part"


@dataclass(frozen=True)
class ForecastPoint:
    period: str
    value: float
    lower: float
    upper: float


@dataclass(frozen=True)
class FeatureRow:
    period: str
    usage: float
    procurement: float
    month: int
    maintenance_count: int
    category: str


def classify_consumption(values: Iterable[float], category: str = "") -> ConsumptionPattern:
    series = [max(0.0, float(value)) for value in values]
    if not series or sum(series) == 0:
        return ConsumptionPattern.SPARE_PART
    zero_ratio = sum(value == 0 for value in series) / len(series)
    average = mean(series)
    variation = pstdev(series) / average if average else 0
    if category.lower() in {"备件", "spare", "spare_part"} or zero_ratio >= 0.6:
        return ConsumptionPattern.SPARE_PART
    if zero_ratio >= 0.25 or variation >= 1.0:
        return ConsumptionPattern.INTERMITTENT
    return ConsumptionPattern.STABLE


def croston(values: Iterable[float], alpha: float = 0.1) -> float:
    series = [max(0.0, float(value)) for value in values]
    non_zero = [(index, value) for index, value in enumerate(series) if value > 0]
    if not non_zero:
        return 0.0
    demand = non_zero[0][1]
    interval = max(1, non_zero[0][0] + 1)
    last_index = non_zero[0][0]
    for index, value in non_zero[1:]:
        gap = index - last_index
        demand = alpha * value + (1 - alpha) * demand
        interval = alpha * gap + (1 - alpha) * interval
        last_index = index
    return demand / max(interval, 1)


def sba(values: Iterable[float], alpha: float = 0.1) -> float:
    return croston(values, alpha) * (1 - alpha / 2)


def build_features(records: Iterable[dict]) -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    for record in records:
        period = str(record["period"])
        rows.append(
            FeatureRow(
                period=period,
                usage=float(record.get("usage", 0)),
                procurement=float(record.get("procurement", 0)),
                month=int(record.get("month", int(period[5:7]) if len(period) > 6 else 1)),
                maintenance_count=int(record.get("maintenance_count", 0)),
                category=str(record.get("category", "未分类")),
            )
        )
    return rows


def forecast_demand(values: Iterable[float], horizon: int = 1, category: str = "") -> tuple[str, list[ForecastPoint]]:
    series = [max(0.0, float(value)) for value in values]
    if horizon < 1:
        raise ValueError("horizon must be positive")
    pattern = classify_consumption(series, category)
    if pattern is ConsumptionPattern.SPARE_PART:
        point = sba(series)
    elif pattern is ConsumptionPattern.INTERMITTENT:
        point = mean(series[-min(3, len(series)) :]) if series else 0.0
    else:
        point = mean(series[-min(3, len(series)) :]) if series else 0.0
    deviation = pstdev(series) if len(series) > 1 else point * 0.2
    return pattern.value, [ForecastPoint(str(index + 1), point, max(0.0, point - 1.96 * deviation), point + 1.96 * deviation) for index in range(horizon)]

