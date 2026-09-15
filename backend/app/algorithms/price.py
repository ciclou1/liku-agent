from dataclasses import dataclass
from enum import StrEnum
from statistics import mean
from typing import Iterable

from app.algorithms.metrics import directional_accuracy

try:
    from lightgbm import LGBMRegressor
except ImportError:
    LGBMRegressor = None


class TimingSignal(StrEnum):
    STOCK_UP = "stock_up"
    DELAY = "delay"
    NORMAL = "normal"


@dataclass(frozen=True)
class PriceForecast:
    sku: str
    periods: list[str]
    prices: list[float]
    direction: str
    signal: TimingSignal
    expected_saving: float
    model_name: str = "LightGBM"


def forecast_price(sku: str, values: Iterable[float], horizon: int = 3, demand_urgency: float = 0.5, holding_cost_rate: float = 0.02, purchase_quantity: float = 1.0) -> PriceForecast:
    series = [max(0.0, float(value)) for value in values]
    if not series or horizon < 1:
        raise ValueError("price series must be non-empty and horizon must be positive")
    recent = mean(series[-min(3, len(series)) :])
    baseline = mean(series)
    trend_window = series[-min(6, len(series)) :]
    slope = (trend_window[-1] - trend_window[0]) / max(len(trend_window) - 1, 1)
    prices, model_name = _predict_prices(series, horizon, recent, slope)
    direction = "up" if slope > baseline * 0.002 else "down" if slope < -baseline * 0.002 else "flat"
    if direction == "up" and demand_urgency < 0.7:
        signal = TimingSignal.STOCK_UP
    elif direction == "down" and demand_urgency < 0.8 and holding_cost_rate < 0.1:
        signal = TimingSignal.DELAY
    else:
        signal = TimingSignal.NORMAL
    if purchase_quantity <= 0:
        saving = 0.0
    elif signal is TimingSignal.STOCK_UP:
        saving = max(0.0, (max(prices) - series[-1]) * purchase_quantity)
    elif signal is TimingSignal.DELAY:
        saving = max(0.0, (series[-1] - min(prices)) * purchase_quantity)
    else:
        saving = 0.0
    return PriceForecast(sku, [str(index + 1) for index in range(horizon)], prices, direction, signal, saving, model_name)


def _predict_prices(series: list[float], horizon: int, recent: float, slope: float) -> tuple[list[float], str]:
    # Tree models interpolate well but cannot extrapolate a rising/falling price
    # beyond the last training date. Use an auditable trend projection first.
    baseline = mean(series)
    if len(series) >= 6 and abs(slope) >= max(baseline * 0.002, 0.0001):
        return ([max(0.0, recent + slope * (index + 1)) for index in range(horizon)], "线性趋势外推")
    if LGBMRegressor is None or len(series) < 6:
        return ([max(0.0, recent + slope * (index + 1)) for index in range(horizon)], "移动平均趋势回退")
    try:
        features = [[index, index % 12] for index in range(len(series))]
        model = LGBMRegressor(n_estimators=80, learning_rate=0.05, max_depth=3, verbosity=-1)
        model.fit(features, series)
        future = [[len(series) + index, (len(series) + index) % 12] for index in range(horizon)]
        return ([max(0.0, float(value)) for value in model.predict(future)], "LightGBM")
    except Exception:
        return ([max(0.0, recent + slope * (index + 1)) for index in range(horizon)], "移动平均趋势回退")


def price_direction_backtest(values: Iterable[float], holdout: int = 1) -> float:
    series = [max(0.0, float(value)) for value in values]
    if len(series) <= holdout or holdout < 1:
        raise ValueError("series must be longer than holdout")
    train, actual = series[:-holdout], series[-holdout:]
    forecast = forecast_price("backtest", train, horizon=holdout).prices
    return directional_accuracy(train[-holdout - 1 :] + actual, train[-holdout - 1 :] + forecast)
