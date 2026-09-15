from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import cos, pi, sin
from statistics import mean
from typing import Iterable

from app.algorithms.demand import ConsumptionPattern, croston, sba

try:
    from lightgbm import LGBMRegressor
except ImportError:
    LGBMRegressor = None

try:
    from statsforecast import StatsForecast
    from statsforecast.models import AutoARIMA, AutoETS
except ImportError:
    StatsForecast = None
    AutoARIMA = None
    AutoETS = None


@dataclass(frozen=True)
class ModelOutput:
    model_name: str
    values: list[float]


class ForecastModel(ABC):
    name: str

    @abstractmethod
    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        raise NotImplementedError


class MovingAverageModel(ForecastModel):
    name = "LightGBM"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        window = values[-min(3, len(values)) :] or [0.0]
        average = sum(window) / len(window)
        return ModelOutput(self.name, [average] * horizon)


class LightGbmModel(MovingAverageModel):
    name = "LightGBM"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        if LGBMRegressor is None or len(values) < 6:
            return ModelOutput(f"{self.name}-fallback", super().predict(values, horizon).values)
        try:
            features = [[index, index % 12] for index in range(len(values))]
            model = LGBMRegressor(n_estimators=60, learning_rate=0.05, max_depth=3, verbosity=-1)
            model.fit(features, values)
            future = [[len(values) + index, (len(values) + index) % 12] for index in range(horizon)]
            return ModelOutput(self.name, [max(0.0, float(value)) for value in model.predict(future)])
        except Exception:
            return ModelOutput(f"{self.name}-fallback", super().predict(values, horizon).values)


class AutoArimaModel(MovingAverageModel):
    name = "AutoARIMA"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        if StatsForecast is None or AutoARIMA is None or len(values) < 4:
            return ModelOutput(f"{self.name}-fallback", super().predict(values, horizon).values)
        import pandas as pd

        history = pd.DataFrame({"unique_id": ["series"] * len(values), "ds": pd.date_range("2020-01-01", periods=len(values), freq="MS"), "y": values})
        result = StatsForecast(models=[AutoARIMA()], freq="MS", n_jobs=1).forecast(horizon, history)
        predicted = [float(value) for value in result["AutoARIMA"].tolist()]
        seasonal = seasonal_trend_forecast(values, horizon)
        if seasonal is not None:
            return ModelOutput("AutoARIMA+趋势季节分解", seasonal)
        return ModelOutput(self.name, predicted)


def seasonal_trend_forecast(values: list[float], horizon: int) -> list[float] | None:
    """Estimate a trend plus a repeating monthly seasonal component.

    Two years of history are enough to compare matching months. The method
    returns None when the seasonal component is too weak, allowing AutoARIMA
    to remain the selected model for non-seasonal demand.
    """
    if len(values) < 12:
        return None
    window = values[-24:]
    period = 12
    overall = mean(window)
    seasonal = [mean([window[index] for index in range(month, len(window), period)]) - overall for month in range(period)]
    seasonal_strength = (sum(value * value for value in seasonal) / period) ** 0.5 / max(overall, 0.0001)
    if seasonal_strength < 0.035:
        return None
    x_values = list(range(len(window)))
    x_mean = mean(x_values)
    y_mean = mean(window)
    denominator = sum((x - x_mean) ** 2 for x in x_values) or 1.0
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, window)) / denominator
    level = y_mean + slope * (len(window) - 1)
    return [max(0.0, level + slope * (index + 1) + seasonal[(len(window) + index) % period]) for index in range(horizon)]


class EtsModel(MovingAverageModel):
    name = "ETS"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        if StatsForecast is not None and AutoETS is not None and len(values) >= 4:
            import pandas as pd

            history = pd.DataFrame({"unique_id": ["series"] * len(values), "ds": pd.date_range("2020-01-01", periods=len(values), freq="MS"), "y": values})
            result = StatsForecast(models=[AutoETS()], freq="MS", n_jobs=1).forecast(horizon, history)
            return ModelOutput(self.name, [float(value) for value in result["AutoETS"].tolist()])
        if not values:
            return ModelOutput(self.name, [0.0] * horizon)
        level = values[0]
        for value in values[1:]:
            level = 0.3 * value + 0.7 * level
        return ModelOutput(self.name, [level] * horizon)


class CrostonModel(ForecastModel):
    name = "Croston"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        return ModelOutput(self.name, [croston(values)] * horizon)


class SbaModel(ForecastModel):
    name = "SBA"

    def predict(self, values: list[float], horizon: int) -> ModelOutput:
        return ModelOutput(self.name, [sba(values)] * horizon)


class ModelPool:
    def __init__(self, models: Iterable[ForecastModel] | None = None) -> None:
        self.models = {model.name: model for model in (models or (AutoArimaModel(), EtsModel(), CrostonModel(), SbaModel(), LightGbmModel()))}

    def select(self, pattern: ConsumptionPattern) -> ForecastModel:
        if pattern is ConsumptionPattern.SPARE_PART:
            return self.models["SBA"]
        if pattern is ConsumptionPattern.INTERMITTENT:
            return self.models["Croston"]
        return self.models["AutoARIMA"]

    def predict(self, values: Iterable[float], horizon: int, pattern: ConsumptionPattern) -> ModelOutput:
        series = [max(0.0, float(value)) for value in values]
        seasonal = seasonal_trend_forecast(series, horizon)
        if seasonal is not None and pattern in {ConsumptionPattern.STABLE, ConsumptionPattern.INTERMITTENT}:
            base_name = self.select(pattern).name
            return ModelOutput(f"{base_name}+趋势季节分解", seasonal)
        return self.select(pattern).predict(series, horizon)
