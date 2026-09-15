"""ErpAnalysisService 结论与核销逻辑（stub 客户端，不依赖真实 ERP）"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.erp.service import ErpAnalysisService
from app.exceptions import BusinessError


class StubClient:
    """按 SQL 特征返回固定行，验证服务层汇总/结论逻辑。"""

    def __init__(self):
        self.queries = []

    def fetch_all(self, sql, params=None, limit=500):
        self.queries.append((" ".join(sql.split()), params, limit))
        s = sql
        if "FROM item" in s:
            return [{"ITEMNUM": "20002183", "DESCRIPTION": "石墨环垫片", "HDMODEL": "Φ", "ISSUEUNIT": "个", "STATUS": "ACTIVE"}]
        if "FROM inventory" in s:
            return [{"STORELOC": "P", "MINLEVEL": 5, "MAXLEVEL": 20, "ISSUEUNIT": "个", "STATUS": "ACTIVE"}]
        if "FROM poline p JOIN po" in s and "SUM(p.ORDERQTY)" in s:
            return [{"contract_lines": 3, "total_qty": 11, "total_cost": 100}]
        if "FROM poline p JOIN po" in s and "received_qty" in s:
            return [{"PONUM": "PO1", "POLINENUM": 1, "SITEID": "PHP", "contract_qty": 4, "received_qty": 1, "in_transit_qty": 3, "STATUS": "APPR"}]
        if "in_transit_qty" in s:
            return [{"in_transit_qty": 3}]
        if "FROM matusetrans" in s and "net_issued_qty" in s:
            return [{"net_issued_qty": 8, "issued_qty": 8, "planned_qty": 10, "returned_qty": 1}]
        if "FROM matusetrans" in s:
            return [{"REFWO": "WO1", "STORELOC": "P", "QUANTITY": -3, "QTYREQUESTED": 4, "CURBAL": 12, "ISSUETYPE": "ISSUE", "ACTUALDATE": "2026-01-01", "ISSUETO": "u", "DESCRIPTION": "d"}]
        if "FROM invbalances" in s:
            return [{"LOCATION": "P", "LOCATION_DESC": "生产物资仓库", "CURBAL": 2, "BINNUM": "B", "LOTNUM": "1"}]
        if "FROM invreserve" in s:
            return [{"LOCATION": "P", "RESERVEDQTY": 1, "ACTUALQTY": 0, "IS_RECIPIENTS": 0, "WONUM": "W1", "RESTYPE": "APHARD", "REQUIREDDATE": None, "WF_STATENAME": None}]
        if "FROM matrectrans" in s:
            return [{"net_received_qty": 9, "received_qty": 10, "returned_qty": -1}]
        if "FROM prline" in s:
            return [{"PRNUM": "PR1", "PRLINENUM": 1, "ITEMNUM": "20002183", "DESCRIPTION": "d", "ORDERQTY": 10, "ORDERUNIT": "个", "ENTERDATE": "2026-04-20", "REQUESTEDBY": None}]
        return []

    def ping(self):
        return True


@pytest.fixture()
def svc():
    service = ErpAnalysisService(client=StubClient())
    return service


def test_conclusion_purchase_when_no_stock():
    class EmptyTransitClient(StubClient):
        def fetch_all(self, sql, params=None, limit=500):
            sql_norm = " ".join(sql.split())
            if "in_transit_qty" in sql_norm and "SUM" in sql_norm and "poline" in sql_norm:
                return [{"in_transit_qty": 0}]
            if "FROM invbalances" in sql_norm:
                return []
            if "FROM invreserve" in sql_norm:
                return []
            return super().fetch_all(sql, params, limit)
    result = ErpAnalysisService(client=EmptyTransitClient()).balance_analysis(itemnum="20002183", request_qty=5)
    assert result["conclusion"]["status"] == "purchase"
    assert result["summary"]["available_qty"] == 0
    # 建议采购 = 申请 5 - 可用 0 = 5（参考值叠加安全库存 5 → 10）
    assert result["conclusion"]["suggested_purchase_qty"] == 5
    assert result["conclusion"]["suggested_purchase_with_safety"] == 10


def test_conclusion_satisfied(svc):
    # 可用量 = 库存 2 + 在途 3 - 预留 1 = 4 >= 申请 4 → 可满足
    result = svc.balance_analysis(itemnum="20002183", request_qty=4)
    assert result["conclusion"]["status"] == "satisfied"
    assert result["summary"]["available_qty"] == 4
    assert result["summary"]["work_order_planned_qty"] == 10
    assert result["dimensions"]["safety_stock"]["total_qty"] == 5


def test_conclusion_partial_and_purchase(svc):
    r = svc.balance_analysis(itemnum="20002183", request_qty=6)
    # 可用量 4 < 申请 6 → 部分满足，建议采购 2
    assert r["conclusion"]["status"] == "partial"
    assert r["conclusion"]["suggested_purchase_qty"] == 2


def test_receipt_return_counts_negative(svc):
    result = svc.balance_analysis(itemnum="20002183", request_qty=1)
    rh = result["dimensions"]["receipt_history"]
    assert rh["returned_qty"] == -1   # 平海口径：入库退库为负数
    assert rh["net_received_qty"] == 9


def test_missing_item_raises():
    class EmptyClient(StubClient):
        def fetch_all(self, sql, params=None, limit=500):
            if "FROM item" in sql:
                return []
            return super().fetch_all(sql, params, limit)
    with pytest.raises(BusinessError):
        ErpAnalysisService(client=EmptyClient()).balance_analysis(itemnum="X")
