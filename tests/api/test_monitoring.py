from fastapi.testclient import TestClient

from app.main import app


def test_readiness_and_prometheus_metrics() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/health/ready").json()["data"]["status"] == "ready"
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "liku_http_requests_total" in metrics.text
        assert "liku_database_ready" in metrics.text
