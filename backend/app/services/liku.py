from app.algorithms.liku import PurchaseInput, calculate_purchase_recommendation, match_transfers, WarehouseStock
from app.data.fixtures import inventory_fixture


class LikuService:
    def recommend(self, payload: dict) -> dict:
        item = PurchaseInput(**{key: payload[key] for key in ("sku", "category", "forecast_demand", "safety_stock", "available_stock", "in_transit", "package_size")})
        result = calculate_purchase_recommendation(item, payload.get("timing_signal", "normal"), payload.get("expected_saving", 0), payload.get("reference_price_low"), payload.get("reference_price_high"))
        return {**result.__dict__, "status": "generated"}

    def transfers(self) -> list[dict]:
        rows = inventory_fixture()
        stocks = [WarehouseStock(row["sku"], row["warehouse_id"], "default", row["available_quantity"], row["safety_stock"], row["unit_cost"]) for row in rows]
        transfers = match_transfers(stocks, {("W1", "W2"): (12, 1), ("W3", "W2"): (18, 2)})
        return [item.__dict__ for item in transfers]
