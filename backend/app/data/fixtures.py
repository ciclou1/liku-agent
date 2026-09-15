from datetime import date, timedelta


def inventory_fixture() -> list[dict]:
    today = date(2026, 9, 8)
    return [
        {"sku": "M12-BOLT", "name": "M12 螺栓", "warehouse_id": "W1", "warehouse_name": "一号仓", "available_quantity": 120, "in_transit": 20, "unit_cost": 1.8, "safety_stock": 80, "last_used_at": today - timedelta(days=30), "expiry_date": None},
        {"sku": "M12-BOLT", "name": "M12 螺栓", "warehouse_id": "W2", "warehouse_name": "二号仓", "available_quantity": 8, "in_transit": 0, "unit_cost": 1.8, "safety_stock": 50, "last_used_at": today - timedelta(days=15), "expiry_date": None},
        {"sku": "CABLE-10", "name": "10mm 电缆", "warehouse_id": "W3", "warehouse_name": "三号仓", "available_quantity": 500, "in_transit": 0, "unit_cost": 28.0, "safety_stock": 120, "last_used_at": today - timedelta(days=450), "expiry_date": today + timedelta(days=20)},
    ]


def usage_fixture(sku: str = "M12-BOLT", warehouse_id: str = "W1") -> list[dict]:
    return [{"period": f"2026-{index:02d}", "usage": value, "procurement": value * 1.2, "month": index, "maintenance_count": index % 3, "category": "紧固件"} for index, value in enumerate([40, 42, 38, 45, 41, 44], 1)]


def price_fixture(sku: str) -> list[float]:
    return [1.7, 1.75, 1.8, 1.86] if sku == "M12-BOLT" else [27.0, 27.8, 28.5, 29.2]

