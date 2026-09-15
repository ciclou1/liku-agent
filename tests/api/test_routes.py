from fastapi.testclient import TestClient
import hashlib
import time
import jwt

from app.main import app


def test_health_and_inventory_api() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.get("/api/v1/inventory?query=M12")
        assert response.status_code == 200
        assert response.json()["data"][0]["sku"] == "M12-BOLT"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_purchase_and_forecast_api() -> None:
    with TestClient(app) as client:
        purchase = client.post("/api/v1/purchase-recommendations", json={"sku": "A", "forecast_demand": 80, "safety_stock": 20, "available_stock": 30, "in_transit": 10, "package_size": 24})
        assert purchase.status_code == 200
        assert purchase.json()["data"]["purchase_quantity"] == 72
        assert purchase.json()["data"]["timing_signal"] in {"stock_up", "delay", "normal"}
        forecast = client.get("/api/v1/forecast/M12-BOLT")
        assert forecast.status_code == 200
        assert len(forecast.json()["data"]["forecast"]) == 12


def test_sql_validation_rejects_write_and_unknown_table() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/sql/validate", params={"query": "DROP TABLE users"}).status_code == 400
        assert client.post("/api/v1/sql/validate", params={"query": "SELECT * FROM secrets"}).status_code == 400
        assert client.post("/api/v1/sql/validate", params={"query": "SELECT * FROM inventory_snapshots"}).status_code == 200


def test_configuration_and_integration_endpoints() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/config/safety-stock", json={"category": "紧固件", "quantity": 80}).status_code == 200
        assert client.post("/api/v1/config/warning-rule", json={"warning_type": "stagnant", "threshold": 365, "level": "warning"}).status_code == 200
        assert client.post("/api/v1/config/price-target", json={"sku": "M12-BOLT", "enabled": True}).status_code == 200
        assert "M12-BOLT" in client.get("/api/v1/config/price-targets").json()["data"]
        sync = client.post("/api/v1/integrations/sync", json={"adapter_name": "api", "mode": "full"})
        assert sync.status_code == 200
        assert sync.json()["data"]["status"] == "completed"


def test_purchase_review_can_adjust_quantity_and_rule_changes_detection() -> None:
    with TestClient(app) as client:
        created = client.post("/api/v1/purchase-recommendations", json={"sku": "REVIEW-A", "forecast_demand": 80, "safety_stock": 20, "available_stock": 30, "in_transit": 10, "package_size": 24})
        row = next(item for item in client.get("/api/v1/purchase-recommendations").json()["data"] if item["sku"] == "REVIEW-A")
        updated = client.patch(f"/api/v1/purchase-recommendations/{row['id']}", json={"purchase_quantity": 48, "status": "reviewed"})
        assert created.status_code == 200
        assert updated.status_code == 200
        assert updated.json()["data"]["purchase_quantity"] == 48
        assert client.post("/api/v1/config/warning-rule", json={"warning_type": "stagnant", "threshold": 30, "level": "critical"}).status_code == 200
        assert client.get("/api/v1/warnings").status_code == 200


def test_task_endpoint_writes_result() -> None:
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", params={"task_type": "sync"}, json={"source": "fixture"})
        assert created.status_code == 200
        task_id = created.json()["data"]["id"]
        current = client.get(f"/api/v1/tasks/{task_id}")
        assert current.json()["data"]["progress"] == 100


def test_open_api_requires_valid_signature() -> None:
    timestamp = str(int(time.time()))
    signature = hashlib.sha256(f"demo-app:{timestamp}:change-me".encode()).hexdigest()
    with TestClient(app) as client:
        assert client.post("/api/v1/open/inventory").status_code == 401
        response = client.post("/api/v1/open/inventory", headers={"X-App-Key": "demo-app", "X-Timestamp": timestamp, "X-Signature": signature})
        assert response.status_code == 200


def test_price_backtest_and_warning_push_api() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/prices/M12-BOLT/backtest").status_code == 200
        pushed = client.post("/api/v1/warnings/push/wecom")
        assert pushed.status_code == 200
        assert pushed.json()["data"]["status"] == "sent"
        assert len(client.get("/api/v1/prices/M12-BOLT/history").json()["data"]) >= 24
        report = client.post("/api/v1/im/feishu/daily-report")
        assert report.json()["data"]["status"] == "sent"


def test_login_returns_signed_jwt() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert response.status_code == 200
        payload = jwt.decode(response.json()["data"]["access_token"], "local-development-secret-change-me", algorithms=["HS256"])
        assert payload["role"] == "manager"


def test_role_data_scope_filters_inventory() -> None:
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "worker", "password": "worker"})
        token = login.json()["data"]["access_token"]
        response = client.get("/api/v1/inventory", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert {row["warehouse_id"] for row in response.json()["data"]} == {"W1"}


def test_sso_adapters_have_common_login_entrypoint() -> None:
    with TestClient(app) as client:
        for provider in ("oidc", "oauth2", "ldap", "cas"):
            response = client.post(f"/api/v1/auth/sso/{provider}", params={"token": "external-user"})
            assert response.status_code == 401


def test_excel_import_endpoint_validates_template() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/integrations/excel/materials", files={"upload": ("materials.xlsx", b"not-an-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert response.status_code == 400
