from fastapi.testclient import TestClient

from app.main import app


def test_chat_session_and_sql_preview() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/v1/chat", json={"message": "M12 螺栓哪个仓库有现货？"})
        session_id = chat.json()["data"]["session_id"]
        assert client.get(f"/api/v1/chat/{session_id}").json()["data"]
        preview = client.post("/api/v1/sql/preview", json={"query": "SELECT sku FROM inventory_snapshots"})
        assert preview.status_code == 200
        assert preview.json()["data"]["tables"] == ["inventory_snapshots"]
