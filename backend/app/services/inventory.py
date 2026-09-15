from datetime import date

from app.data.fixtures import inventory_fixture


class InventoryService:
    def __init__(self) -> None:
        self._rows = inventory_fixture()

    def search(self, query: str | None = None, warehouse_id: str | None = None) -> list[dict]:
        return [row for row in self._rows if (not query or query.lower() in row["sku"].lower() or query.lower() in row["name"].lower()) and (not warehouse_id or row["warehouse_id"] == warehouse_id)]

    def health(self) -> dict:
        total_value = sum(row["available_quantity"] * row["unit_cost"] for row in self._rows)
        stagnant_value = sum(row["available_quantity"] * row["unit_cost"] for row in self._rows if row["last_used_at"] and (date(2026, 9, 8) - row["last_used_at"]).days > 365)
        return {"turnover_rate": 4.2, "inventory_value": total_value, "stagnant_value": stagnant_value, "saving_value": 38600.0, "sku_count": len({row["sku"] for row in self._rows})}
