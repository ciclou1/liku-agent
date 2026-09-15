from fastapi.testclient import TestClient

from app.main import app


def test_transfer_routes_and_dashboard_metrics_are_nonzero() -> None:
    with TestClient(app) as client:
        transfers = client.get("/api/v1/transfers", params={"sku": "DEMO-MAT-002", "target_warehouse_id": "W1", "min_quantity": 1})
        assert transfers.status_code == 200
        assert transfers.json()["data"]
        row = transfers.json()["data"][0]
        assert row["distance_km"] > 0
        assert row["lead_time_days"] > 0

        dashboard = client.get("/api/v1/dashboard/health")
        assert dashboard.status_code == 200
        assert dashboard.json()["data"]["turnover_rate"] > 0
        assert dashboard.json()["data"]["saving_value"] > 0
