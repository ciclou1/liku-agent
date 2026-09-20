"""呆滞识别 / 安全库存优化 API 与智能问答新意图（TestClient，sqlite 夹具库）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient

from app.main import app
from app.services.chatbot import format_tool_facts


def test_dormant_endpoint_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/dormant", params={"threshold_days": 365, "size": 20})
        assert response.status_code == 200
        data = response.json()["data"]
        assert {"items", "total", "summary", "page_amount"} <= set(data)
        for item in data["items"]:
            assert item["suggestion"] in {"调剂", "退货", "报废评估"}
            assert item["amount"] >= 0
            assert item["basis"]


def test_dormant_export_returns_xlsx() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/dormant/export")
        assert response.status_code == 200
        assert "spreadsheetml" in response.headers["content-type"]


def test_replenishment_detail_and_batch() -> None:
    with TestClient(app) as client:
        detail = client.get("/api/v1/replenishment/M12-BOLT", params={"lead_time_months": 1})
        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["sku"] == "M12-BOLT"
        assert data["lead_time_source"] == "manual"
        if not data["insufficient_data"]:
            assert {"mu_monthly", "suggested_safety", "reorder_point", "reorder_quantity", "formula_explanation"} <= set(data)
        batch = client.get("/api/v1/replenishment", params={"limit": 20})
        assert batch.status_code == 200
        assert "items" in batch.json()["data"]
        # 导出路由不能被 /replenishment/{sku} 抢占
        export = client.get("/api/v1/replenishment/export")
        assert export.status_code == 200
        assert "spreadsheetml" in export.headers["content-type"]


def test_chat_routes_to_inventory_stats() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "帮我生成一份库存统计报表"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["tool_name"] == "query_inventory_stats"
        assert "库存总金额" in data["answer"]


def test_chat_routes_to_consumption() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "最近消耗情况怎么样？"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["tool_name"] == "query_consumption"


def test_chat_arrival_rate_degrades_when_erp_down(monkeypatch) -> None:
    from app.services import chatbot as chatbot_module

    class BrokenErp:
        def arrival_rate(self, *args, **kwargs):
            raise ConnectionError("erp unreachable")

    monkeypatch.setattr(chatbot_module, "ErpAnalysisService", BrokenErp)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "M12-BOLT 的到货率如何？"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["tool_name"] == "query_arrival_rate"
        assert "暂时不可达" in data["answer"]


def test_arrival_facts_formatting() -> None:
    facts = format_tool_facts("query_arrival_rate", {
        "overall_rate": 0.8, "contracts": 5, "total_ordered": 100, "total_received": 80,
        "by_item": [{"ITEMNUM": "20002183", "rate": 0.6}],
        "by_supplier": [{"VENDOR": "甲", "rate": 1.0}],
        "formula_explanation": "口径说明",
    })
    assert "80.0%" in facts and "甲" in facts
    assert "全部历史" in facts and "5 份合同" in facts
    windowed = format_tool_facts("query_arrival_rate", {
        "overall_rate": 0.5, "contracts": 2, "total_ordered": 10, "total_received": 5,
        "by_item": [], "by_supplier": [], "start": "2024-01-01", "end": "2024-12-31",
        "window_applied": True,
    })
    assert "2024-01-01 ~ 2024-12-31" in windowed
    none_facts = format_tool_facts("query_arrival_rate", {"overall_rate": None, "by_month": [], "by_supplier": []})
    assert "无法计算" in none_facts
    stats = format_tool_facts("query_inventory_stats", {
        "inventory_value": 87580000, "sku_count": 23000, "stagnant_value": 120000,
        "turnover_rate": 1.2, "saving_value": 5000,
        "warehouses": [{"warehouse_name": "生产物资仓库", "amount": 100}],
    })
    assert "87580000" in stats and "生产物资仓库" in stats
