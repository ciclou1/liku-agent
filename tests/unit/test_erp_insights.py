"""ErpAnalysisService 到货率 / 供应交期查询（stub 客户端，不依赖真实 ERP）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.erp.service import ErpAnalysisService


class InsightsStubClient:
    """按 SQL 特征返回固定行（到货率与交期共用）。"""

    def __init__(self, lead_rows=None, ordered_total=100, received_total=80):
        self.queries = []
        self.lead_rows = lead_rows or []
        self.ordered_total = ordered_total
        self.received_total = received_total

    def fetch_all(self, sql, params=None, limit=500):
        normalized = " ".join(sql.split())
        self.queries.append((normalized, params))
        # ── 到货率 ──
        if "AS contracts" in normalized:
            return [{"ordered_qty": self.ordered_total, "contracts": 5}]
        if "received_qty FROM matrectrans m" in normalized:
            if "m.ITEMNUM IN" in normalized:
                return [{"ITEMNUM": "20002183", "received_qty": 60}]
            if "GROUP BY VENDOR" in normalized:
                return [{"VENDOR": "甲供应商", "received_qty": 70}]
            return [{"received_qty": self.received_total}]
        if "GROUP BY p.ITEMNUM ORDER BY ordered_qty DESC" in normalized:
            return [{"ITEMNUM": "20002183", "ordered_qty": 100}]
        if "GROUP BY VENDOR ORDER BY ordered_qty DESC" in normalized:
            return [{"VENDOR": "甲供应商", "ordered_qty": 70}]
        # ── 交期 ──
        if "first_receipt" in normalized:
            return self.lead_rows
        return []

    def ping(self):
        return True


def _query(client, marker, *, exclude=None):
    return next((sql for sql, _params in client.queries if marker in sql and (not exclude or exclude not in sql)), "")


# ────────── 到货率 ──────────

def test_arrival_rate_overall_and_breakdown():
    svc = ErpAnalysisService(client=InsightsStubClient())
    result = svc.arrival_rate(itemnum="20002183")
    assert result["overall_rate"] == 0.8
    assert result["total_ordered"] == 100 and result["total_received"] == 80
    assert result["by_item"][0]["ITEMNUM"] == "20002183"
    assert result["by_item"][0]["rate"] == 0.6
    assert result["by_supplier"][0]["rate"] == 1.0


def test_arrival_rate_omits_unreliable_month_breakdown():
    """ERP 下单日期多为“1 月 1 日”占位值，按月聚合成误导趋势，故不提供月度拆分。"""
    result = ErpAnalysisService(client=InsightsStubClient()).arrival_rate(itemnum="20002183")
    assert "by_month" not in result


def test_arrival_rate_has_no_default_window():
    """回归：曾默认按近 12 个月过滤，而 ERP 合同数据止于 2025 年初，
    导致任何物资的到货率都返回“无法计算”。"""
    client = InsightsStubClient()
    result = ErpAnalysisService(client=client).arrival_rate(itemnum="20002183")
    assert result["window_applied"] is False
    assert result["start"] is None and result["end"] is None
    ordered_sql = _query(client, "AS contracts")
    assert "COALESCE(po.ORDERDATE, po.STARTDATE) >=" not in ordered_sql
    assert "COALESCE(po.ORDERDATE, po.STARTDATE) <=" not in ordered_sql


def test_arrival_rate_sql_scope_differs_between_sides():
    """合同侧带 SITEID；入库侧不带（入库多记在 PDSITE），但按 ITEMNUM 汇总。"""
    client = InsightsStubClient()
    ErpAnalysisService(client=client).arrival_rate(itemnum="20002183", supplier="甲")
    ordered_sql, ordered_params = client.queries[0]
    assert "po.SITEID = %s" in ordered_sql
    assert "p.ITEMNUM = %s" in ordered_sql
    assert "po.VENDOR LIKE %s" in ordered_sql
    assert "WAPPR" in ordered_sql
    assert ordered_params[0] == "PHP"
    received_sql = _query(client, "received_qty FROM matrectrans m", exclude="m.ITEMNUM IN")
    assert "SITEID" not in received_sql
    assert "m.ITEMNUM = %s" in received_sql


def test_arrival_rate_window_filters_both_sides_when_given():
    from datetime import date

    client = InsightsStubClient()
    result = ErpAnalysisService(client=client).arrival_rate(
        itemnum="20002183", start=date(2024, 1, 1), end=date(2024, 12, 31))
    assert result["window_applied"] is True
    assert result["start"] == "2024-01-01" and result["end"] == "2024-12-31"
    assert "COALESCE(po.ORDERDATE, po.STARTDATE) >= %s" in _query(client, "AS contracts")
    assert "m.ACTUALDATE >= %s" in _query(client, "received_qty FROM matrectrans m", exclude="m.ITEMNUM IN")


def test_arrival_rate_zero_denominator_returns_none():
    class EmptyClient(InsightsStubClient):
        def fetch_all(self, sql, params=None, limit=500):
            normalized = " ".join(sql.split())
            self.queries.append((normalized, params))
            if "AS contracts" in normalized:
                return [{"ordered_qty": 0, "contracts": 0}]
            return []

    result = ErpAnalysisService(client=EmptyClient()).arrival_rate(itemnum="X")
    assert result["overall_rate"] is None
    assert result["by_item"] == []
    assert result["contracts"] == 0


def test_arrival_rate_handles_empty_aggregate_rows():
    """聚合查询异常返回空集时不应抛 IndexError。"""
    class NoRowsClient(InsightsStubClient):
        def fetch_all(self, sql, params=None, limit=500):
            self.queries.append((" ".join(sql.split()), params))
            return []

    result = ErpAnalysisService(client=NoRowsClient()).arrival_rate(itemnum="X")
    assert result["total_ordered"] == 0 and result["total_received"] == 0
    assert result["overall_rate"] is None


# ────────── 供应交期 ──────────

def test_lead_time_sql_joins_po_by_receipt_pnum():
    client = InsightsStubClient(lead_rows=[{"GROUP_KEY": "20002183", "lead_months": 5.9, "min_days": 20, "max_days": 260, "samples": 8}])
    result = ErpAnalysisService(client=client).lead_time(itemnum="20002183")
    sql, params = client.queries[0]
    # 入库流水按 PONUM 关联 po（poline 行级命中率为 0；入库记在 PDSITE、合同在 PHP，不能用 SITEID）
    assert "JOIN po ON po.PONUM = m.PONUM " in sql
    assert "poline" not in sql
    assert "GROUP BY PONUM" in sql
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


def test_lead_time_supplier_dimension():
    rows = [{"GROUP_KEY": "甲供应商", "lead_months": 2.0, "min_days": 30, "max_days": 90, "samples": 5}]
    result = ErpAnalysisService(client=InsightsStubClient(lead_rows=rows)).lead_time(supplier="甲")
    assert result["dimension"] == "supplier"
    assert result["lead_months"] == 2.0


def test_lead_time_miss_returns_none():
    result = ErpAnalysisService(client=InsightsStubClient(lead_rows=[])).lead_time(itemnum="NOPE")
    assert result is None
