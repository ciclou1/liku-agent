from fastapi.testclient import TestClient

from app.main import app


def test_planning_features_use_database_seed() -> None:
    with TestClient(app) as client:
        materials = client.get("/api/v1/materials")
        assert materials.status_code == 200
        assert len(materials.json()["data"]) >= 15

        purchase = client.post("/api/v1/purchase-recommendations/generate", json={"sku": "DEMO-MAT-001", "warehouse_id": "W2"})
        assert purchase.status_code == 200
        assert purchase.json()["data"]["data_source"] == "mysql"
        assert purchase.json()["data"]["purchase_quantity"] > 0

        transfers = client.get("/api/v1/transfers", params={"sku": "DEMO-MAT-001", "target_warehouse_id": "W2", "min_quantity": 1})
        assert transfers.status_code == 200
        assert transfers.json()["data"][0]["target_warehouse_id"] == "W2"

        forecast = client.get("/api/v1/forecast/DEMO-MAT-001", params={"warehouse_id": "W1"})
        assert forecast.status_code == 200
        assert len(forecast.json()["data"]["history"]) >= 24
        assert len(forecast.json()["data"]["forecast"]) == 12
        values = [round(item["value"], 3) for item in forecast.json()["data"]["forecast"]]
        assert len(set(values)) > 1

        prices = client.get("/api/v1/prices/DEMO-MAT-001")
        assert prices.status_code == 200
        assert len(prices.json()["data"]["history"]) >= 24
        assert len(prices.json()["data"]["periods"]) == 3
