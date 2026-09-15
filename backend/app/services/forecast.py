from app.algorithms.backtest import backtest
from app.algorithms.demand import build_features, forecast_demand
from app.algorithms.demand import ConsumptionPattern, ForecastPoint, classify_consumption
from app.algorithms.model_pool import ModelPool
from app.data.fixtures import usage_fixture


class ForecastService:
    def get(self, sku: str, warehouse_id: str) -> dict:
        records = usage_fixture(sku, warehouse_id)
        values = [item["usage"] for item in records]
        pattern = classify_consumption(values, records[0].get("category", ""))
        model = ModelPool().select(pattern)
        output = model.predict(values, 12)
        deviation = (sum((value - sum(values) / len(values)) ** 2 for value in values) / len(values)) ** 0.5 if values else 0
        forecast = [ForecastPoint(str(index + 1), value, max(0, value - 1.96 * deviation), value + 1.96 * deviation) for index, value in enumerate(output.values)]
        report = backtest([item["usage"] for item in records])
        return {"sku": sku, "warehouse_id": warehouse_id, "pattern": pattern.value, "history": [item.__dict__ for item in build_features(records)], "forecast": [point.__dict__ for point in forecast], "corrected": False, "model_name": output.model_name, "backtest": report.__dict__}

    def correct(self, sku: str, warehouse_id: str, values: list[float]) -> dict:
        pattern, forecast = forecast_demand(values, horizon=12)
        return {"sku": sku, "warehouse_id": warehouse_id, "pattern": pattern, "history": [{"period": str(index + 1), "usage": value} for index, value in enumerate(values)], "forecast": [point.__dict__ for point in forecast], "corrected": True}
