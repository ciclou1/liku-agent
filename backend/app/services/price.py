from datetime import date, timedelta

from app.algorithms.price import forecast_price, price_direction_backtest
from app.data.fixtures import price_fixture


class PriceService:
    def history(self, sku: str) -> list[dict[str, str | float]]:
        values = price_fixture(sku)
        return [{"sku": sku, "supplier": f"供应商-{index % 2 + 1}", "price": value, "recorded_at": (date(2026, 5, 1) + timedelta(days=index * 30)).isoformat()} for index, value in enumerate(values)]

    def get(self, sku: str, purchase_quantity: float = 1.0) -> dict:
        result = forecast_price(sku, price_fixture(sku), purchase_quantity=purchase_quantity)
        return result.__dict__ | {"signal": result.signal.value, "history": self.history(sku), "backtest": self.backtest(sku)}

    def backtest(self, sku: str) -> dict[str, float | str]:
        values = price_fixture(sku)
        return {"sku": sku, "directional_accuracy": price_direction_backtest(values), "sample_count": len(values)}
