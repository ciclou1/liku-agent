"""ErpAnalysisService 到货率 / 供应交期查询（stub 客户端，不依赖真实 ERP）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.erp.service import ErpAnalysisService


class InsightsStubClient:
    """按 SQL 特征返回固定行。"""

    def __init__(self, lead_rows=None):
        self.queries = []
        self.lead_rows = lead_rows or []

    def fetch_all(self, sql, params=None, limit=500):
        normalized = " ".join(sql.split())
        self.queries.append((normalized, params))
        if "total_ordered" in normalized:
            return [{"total_ordered": 100, "total_received": 80, "contract_lines": 5}]
        if "GROUP BY MONTH" in normalized:
            return [{"MONTH": "2026-08", "ordered_qty": 60, "received_qty": 30},
                    {"MONTH": "2026-07", "ordered_qty": 40, "received_qty": 40}]
        if "GROUP BY VENDOR" in normalized:
            return [{"VENDOR": "甲供应商", "ordered_qty": 70, "received_qty": 70},
                    {"VENDOR": "乙供应商", "ordered_qty": 30, "received_qty": 10}]
        if "GROUP BY p.ITEMNUM" in normalized:
            return [{"ITEMNUM": "20002183", "ordered_qty": 100, "received_qty": 80}]
        if "first_receipt" in normalized:
            return self.lead_rows
        if "po.VENDOR FROM poline" in normalized:
            return [{"VENDOR": "甲供应商"}]
        return []

    def ping(self):
        return True


def test_arrival_rate_overall_and_breakdown():
    svc = ErpAnalysisService(client=InsightsStubClient())
    result = svc.arrival_rate(itemnum="20002183")
    assert result["overall_rate"] == 0.8
    assert result["total_ordered"] == 100 and result["total_received"] == 80
    assert result["by_month"][0]["rate"] == 0.5
    assert result["by_supplier"][0]["rate"] == 1.0
    assert result["by_item"][0]["ITEMNUM"] == "20002183"


def test_arrival_rate_sql_carries_site_and_filters():
    client = InsightsStubClient()
    svc = ErpAnalysisService(client=client)
    svc.arrival_rate(itemnum="20002183", supplier="甲")
    totals_sql, totals_params = client.queries[0]
    assert totals_params[0] == "PHP"
    assert "po.SITEID = %s" in totals_sql
    assert "p.ITEMNUM = %s" in totals_sql
    assert "po.VENDOR LIKE %s" in totals_sql
    assert "WAPPR" in totals_sql


def test_arrival_rate_zero_denominator_returns_none():
    class EmptyClient(InsightsStubClient):
        def fetch_all(self, sql, params=None, limit=500):
            normalized = " ".join(sql.split())
            if "total_ordered" in normalized:
                return [{"total_ordered": 0, "total_received": 0, "contract_lines": 0}]
            if "GROUP BY MONTH" in normalized or "GROUP BY VENDOR" in normalized or "GROUP BY p.ITEMNUM" in normalized:
                return []
            return []
    result = ErpAnalysisService(client=EmptyClient()).arrival_rate(itemnum="X")
    assert result["overall_rate"] is None
    assert result["by_month"] == []


def test_lead_time_item_dimension_hit():
    rows = [{"GROUP_KEY": "20002183", "lead_months": 1.5, "min_days": 20, "max_days": 60, "samples": 8}]
    result = ErpAnalysisService(client=InsightsStubClient(lead_rows=rows)).lead_time(itemnum="20002183")
    assert result["dimension"] == "item"
    assert result["lead_months"] == 1.5
    assert result["samples"] == 8


def test_lead_time_sql_joins_po_by_receipt_pnum():
    client = InsightsStubClient(lead_rows=[{"GROUP_KEY": "20002183", "lead_months": 5.9, "min_days": 20, "max_days": 260, "samples": 8}])
    result = ErpAnalysisService(client=client).lead_time(itemnum="20002183")
    sql, params = client.queries[0]
    # 入库流水按 PONUM 关联 po（poline 行级命中率为 0；入库记在 PDSITE、合同在 PHP，不能用 SITEID）
    assert "JOIN po ON po.PONUM = m.PONUM " in sql
    assert "poline" not in sql
    assert "m.ITEMNUM = %s" in sql
    assert "20002183" in params
    assert result["dimension"] == "item"
    assert result["lead_months"] == 5.9


def test_lead_time_falls_back_to_site_average():
    class SiteClient(InsightsStubClient):
        def fetch_all(self, sql, params=None, limit=500):
            normalized = " ".join(sql.split())
            self.queries.append((normalized, params))
            if "GROUP_KEY" not in normalized and "lead_months" in normalized:
                return [{"lead_months": 5.85, "min_days": 1, "max_days": 400, "samples": 29781}]
            return []

    result = ErpAnalysisService(client=SiteClient()).lead_time(itemnum="NOPE")
    assert result["dimension"] == "site"
    assert result["lead_months"] == 5.85
    assert result["samples"] == 29781


def test_lead_time_falls_back_to_supplier_dimension():
    rows = [{"GROUP_KEY": "甲供应商", "lead_months": 2.0, "min_days": 30, "max_days": 90, "samples": 5}]
    result = ErpAnalysisService(client=InsightsStubClient(lead_rows=rows)).lead_time(supplier="甲")
    assert result["dimension"] == "supplier"
    assert result["lead_months"] == 2.0


def test_lead_time_miss_returns_none():
    result = ErpAnalysisService(client=InsightsStubClient(lead_rows=[])).lead_time(itemnum="NOPE")
    assert result is None
