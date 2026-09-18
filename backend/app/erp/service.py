"""平衡利库六维度分析服务（口径对齐《物资AI分析.pptx》）。

维度与数据源（全部只读 ERP）：
- 历史采购量：po/poline 采购合同行按物资编码汇总（排除 WAPPR 未批准、CAN 已取消）
- 在途量：口径已定为 合同数量 - 入库数量（poline.ORDERQTY - RECEIVEDQTY，仅统计未关闭合同）
- 工单领用量：matusetrans 领用发放汇总（ISSUE 为负数，取反汇总；退料 RETURN 为正数）
- 库存量：invbalances.CURBAL 按库房汇总
- 预留量：invreserve.RESERVEDQTY（IS_DEL=0）
- 安全库存量：inventory.MINLEVEL（主库存项目最低库存/重订购点）
符号约定（实测）：matrectrans 入库 RECEIPT 为正、入库退库 RETURN 为负（平海口径：退库计入入库统计负数）；
matusetrans 领用 ISSUE 为负、退料 RETURN 为正。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import get_settings
from app.erp.client import ErpClient, ErpQueryError

# 视为有效合同的 po.STATUS（排除未批准与已取消）
_VALID_PO_EXCLUDE = ("'WAPPR'", "'CAN'")
_OPEN_PO_EXCLUDE = ("'CLOSE'", "'CAN'", "'CLOSED'", "'WAPPR'")

# 到货/入库核销子查询：matrectrans RECEIPT/RETURN 按 合同行 聚合（RETURN 为负自动冲减）
_RECEIVED_NOTE = "receipt join uses PONUM+POLINENUM only"
_RECEIVED_AGG = (
    "LEFT JOIN (SELECT PONUM, POLINENUM, SUM(QUANTITY) AS received_qty "
    "FROM matrectrans WHERE ISSUETYPE IN ('RECEIPT', 'RETURN') "
    "GROUP BY PONUM, POLINENUM) r "
    "ON r.PONUM = p.PONUM AND r.POLINENUM = p.POLINENUM"
)


class ErpAnalysisService:
    def __init__(self, client: ErpClient | None = None) -> None:
        self.client = client or ErpClient()

    # ---------- 单维度查询 ----------

    def item_info(self, itemnum: str, site_id: str) -> dict[str, Any]:
        rows = self.client.fetch_all(
            "SELECT ITEMNUM, DESCRIPTION, HDMODEL, ISSUEUNIT, STATUS FROM item WHERE ITEMNUM = %s LIMIT 1",
            [itemnum],
            limit=1,
        )
        if not rows:
            raise ErpQueryError(f"物料 {itemnum} 在 ERP 中不存在")
        info = dict(rows[0])
        inv_rows = self.client.fetch_all(
            "SELECT STORELOC, MINLEVEL, MAXLEVEL, ISSUEUNIT, STATUS FROM inventory "
            "WHERE ITEMNUM = %s AND SITEID = %s",
            [itemnum, site_id],
        )
        info["inventory_records"] = inv_rows
        info["safety_stock"] = sum(float(r.get("MINLEVEL") or 0) for r in inv_rows)
        return info

    def history_purchase(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """历史采购量：所有有效采购合同条目数量合计（合同联接带 SITEID，防跨站点同号串数据）。"""
        join = "JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID"
        totals = self.client.fetch_all(
            "SELECT COUNT(*) AS contract_lines, COALESCE(SUM(p.ORDERQTY), 0) AS total_qty, "
            "COALESCE(SUM(p.LINECOST), 0) AS total_cost "
            f"FROM poline p {join} "
            f"WHERE p.ITEMNUM = %s AND po.SITEID = %s AND po.STATUS NOT IN ({','.join(_VALID_PO_EXCLUDE)})",
            [itemnum, site_id],
            limit=1,
        )[0]
        details = self.client.fetch_all(
            "SELECT p.PONUM, p.POLINENUM, p.SITEID, p.ORDERQTY, p.UNITCOST, p.LINECOST, p.RECEIVEDQTY, "
            "po.STATUS, po.DESCRIPTION, po.STARTDATE "
            f"FROM poline p {join} "
            f"WHERE p.ITEMNUM = %s AND po.SITEID = %s AND po.STATUS NOT IN ({','.join(_VALID_PO_EXCLUDE)}) "
            "ORDER BY po.STARTDATE DESC",
            [itemnum, site_id],
            limit=100,
        )
        return {"total_qty": float(totals["total_qty"] or 0), "contract_lines": int(totals["contract_lines"] or 0), "total_cost": float(totals["total_cost"] or 0), "details": details}

    def in_transit(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """在途量 = 合同数量 − 入库数量（已定口径：按 PONUM+POLINENUM+SITEID 聚合
        matrectrans 入库/入库退库流水核销；退库流水为负数自动冲减；负值按 0 计）。"""
        join = "JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID"
        receipt_agg = (
            "LEFT JOIN (SELECT PONUM, POLINENUM, SITEID, SUM(QUANTITY) AS received_qty "
            "FROM matrectrans WHERE ISSUETYPE IN ('RECEIPT', 'RETURN') "
            "GROUP BY PONUM, POLINENUM, SITEID) r "
            "ON r.PONUM = p.PONUM AND r.POLINENUM = p.POLINENUM AND r.SITEID = p.SITEID"
        )
        gap_expr = "CASE WHEN p.ORDERQTY - COALESCE(r.received_qty, 0) < 0 THEN 0 ELSE p.ORDERQTY - COALESCE(r.received_qty, 0) END"
        totals = self.client.fetch_all(
            f"SELECT COALESCE(SUM({gap_expr}), 0) AS in_transit_qty "
            f"FROM poline p {join} {receipt_agg} "
            f"WHERE p.ITEMNUM = %s AND po.SITEID = %s AND po.STATUS NOT IN ({','.join(_OPEN_PO_EXCLUDE)})",
            [itemnum, site_id],
            limit=1,
        )[0]
        details = self.client.fetch_all(
            f"SELECT p.PONUM, p.POLINENUM, p.SITEID, p.ORDERQTY AS contract_qty, "
            f"COALESCE(r.received_qty, 0) AS received_qty, "
            f"{gap_expr} AS in_transit_qty, "
            "po.STATUS "
            f"FROM poline p {join} {receipt_agg} "
            f"WHERE p.ITEMNUM = %s AND po.SITEID = %s AND po.STATUS NOT IN ({','.join(_OPEN_PO_EXCLUDE)}) "
            "ORDER BY in_transit_qty DESC",
            [itemnum, site_id],
            limit=100,
        )
        return {"in_transit_qty": float(totals["in_transit_qty"] or 0), "open_lines": len(details), "details": details}

    def work_order_usage(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """工单领用：实际领用（ISSUE，QUANTITY 为负取反）、计划数量（QTYREQUESTED）、退料（RETURN）。"""
        summary = self.client.fetch_all(
            "SELECT COALESCE(SUM(CASE WHEN ISSUETYPE = 'ISSUE' THEN -QUANTITY ELSE QUANTITY END), 0) AS net_issued_qty, "
            "COALESCE(SUM(CASE WHEN ISSUETYPE = 'ISSUE' THEN -QUANTITY ELSE 0 END), 0) AS issued_qty, "
            "COALESCE(SUM(CASE WHEN ISSUETYPE = 'ISSUE' THEN QTYREQUESTED ELSE 0 END), 0) AS planned_qty, "
            "COALESCE(SUM(CASE WHEN ISSUETYPE = 'RETURN' THEN QUANTITY ELSE 0 END), 0) AS returned_qty "
            "FROM matusetrans WHERE ITEMNUM = %s AND SITEID = %s",
            [itemnum, site_id],
            limit=1,
        )[0]
        details = self.client.fetch_all(
            "SELECT REFWO, STORELOC, QUANTITY, QTYREQUESTED, CURBAL, ISSUETYPE, ACTUALDATE, ISSUETO, LEFT(DESCRIPTION, 60) AS DESCRIPTION "
            "FROM matusetrans WHERE ITEMNUM = %s AND SITEID = %s ORDER BY ACTUALDATE DESC",
            [itemnum, site_id],
            limit=100,
        )
        return {
            "issued_qty": float(summary["issued_qty"] or 0),
            "planned_qty": float(summary["planned_qty"] or 0),
            "returned_qty": float(summary["returned_qty"] or 0),
            "net_issued_qty": float(summary["net_issued_qty"] or 0),
            "details": details,
        }

    def stock_balance(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """库存量：invbalances 当前余量按库房。"""
        rows = self.client.fetch_all(
            "SELECT b.LOCATION, l.DESCRIPTION AS LOCATION_DESC, b.CURBAL, b.BINNUM, b.LOTNUM "
            "FROM invbalances b LEFT JOIN locations l ON l.LOCATION = b.LOCATION AND l.SITEID = b.SITEID "
            "WHERE b.ITEMNUM = %s AND b.SITEID = %s AND COALESCE(b.is_del, 0) = 0 ORDER BY b.CURBAL DESC",
            [itemnum, site_id],
        )
        total = sum(float(r.get("CURBAL") or 0) for r in rows)
        return {"total_qty": total, "details": rows}

    def reservations(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """预留量：invreserve.RESERVEDQTY（未删除）。"""
        rows = self.client.fetch_all(
            "SELECT LOCATION, RESERVEDQTY, ACTUALQTY, IS_RECIPIENTS, WONUM, RESTYPE, REQUIREDDATE, WF_STATENAME "
            "FROM invreserve WHERE ITEMNUM = %s AND SITEID = %s AND COALESCE(IS_DEL, 0) = 0 "
            "ORDER BY RESERVEDQTY DESC",
            [itemnum, site_id],
        )
        total = sum(float(r.get("RESERVEDQTY") or 0) for r in rows)
        return {"total_qty": total, "details": rows}

    def receipt_history(self, itemnum: str, site_id: str) -> dict[str, Any]:
        """入库/入库退库流水（RETURN 已为负数，平海口径）。"""
        summary = self.client.fetch_all(
            "SELECT COALESCE(SUM(QUANTITY), 0) AS net_received_qty, "
            "COALESCE(SUM(CASE WHEN ISSUETYPE = 'RECEIPT' THEN QUANTITY ELSE 0 END), 0) AS received_qty, "
            "COALESCE(SUM(CASE WHEN ISSUETYPE = 'RETURN' THEN QUANTITY ELSE 0 END), 0) AS returned_qty "
            "FROM matrectrans WHERE ITEMNUM = %s AND SITEID = %s",
            [itemnum, site_id],
            limit=1,
        )[0]
        return {
            "received_qty": float(summary["received_qty"] or 0),
            "returned_qty": float(summary["returned_qty"] or 0),
            "net_received_qty": float(summary["net_received_qty"] or 0),
        }

    def price_history(self, itemnum: str, site_id: str) -> list[dict[str, Any]]:
        """采购入库实际单价历史，作为本地价格快照缺失时的只读回退。"""
        return self.client.fetch_all(
            "SELECT ITEMNUM, COALESCE(NULLIF(PONUM, ''), 'ERP') AS SUPPLIER, "
            "UNITCOST AS PRICE, ACTUALDATE AS RECORDED_AT "
            "FROM matrectrans WHERE ITEMNUM = %s AND SITEID = %s "
            "AND ISSUETYPE = 'RECEIPT' AND UNITCOST > 0 AND ACTUALDATE IS NOT NULL "
            "ORDER BY ACTUALDATE",
            [itemnum, site_id], limit=200,
        )

    # ---------- 到货率与供应交期（库存智能问答 / 安全库存优化用） ----------

    @staticmethod
    def _arrival_where(itemnum: str | None, supplier: str | None, start: date | None, end: date | None) -> tuple[str, list[Any]]:
        """到货率共用的 WHERE 与参数（供应商为模糊匹配，LIKE 已转义）。"""
        where = f"po.SITEID = %s AND po.STATUS NOT IN ({','.join(_VALID_PO_EXCLUDE)}) AND p.ITEMNUM IS NOT NULL"
        params: list[Any] = [get_settings().erp_site_id]
        if itemnum:
            where += " AND p.ITEMNUM = %s"
            params.append(itemnum)
        if supplier:
            where += " AND po.VENDOR LIKE %s"
            params.append(f"%{ErpAnalysisService._escape_like(supplier)}%")
        if start:
            where += " AND COALESCE(po.ORDERDATE, po.STARTDATE) >= %s"
            params.append(start)
        if end:
            where += " AND COALESCE(po.ORDERDATE, po.STARTDATE) <= %s"
            params.append(end)
        return where, params

    def arrival_rate(self, itemnum: str | None = None, supplier: str | None = None,
                     start: date | None = None, end: date | None = None) -> dict[str, Any]:
        """到货率 = Σ已入库 / Σ合同数量（数量口径，仅有效合同；入库按 matrectrans 流水核销）。

        支持物资/供应商（模糊）/时间段三个维度；未指定时间段时默认统计近 12 个月
        （ERP 入库流水仅覆盖近年，全历史口径会因合同多、流水少而严重失真）；
        分母为 0 时 overall_rate 返回 None（不除零）。
        """
        window_applied = start is None and end is None
        if window_applied:
            from datetime import timedelta
            start = date.today() - timedelta(days=365)
        where, params = self._arrival_where(itemnum, supplier, start, end)
        totals = self.client.fetch_all(
            "SELECT COALESCE(SUM(p.ORDERQTY), 0) AS total_ordered, "
            "COALESCE(SUM(CASE WHEN COALESCE(r.received_qty, 0) < 0 THEN 0 ELSE COALESCE(r.received_qty, 0) END), 0) AS total_received, "
            "COUNT(*) AS contract_lines "
            f"FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID {_RECEIVED_AGG} "
            f"WHERE {where} LIMIT 1",
            params, limit=1,
        )[0]
        ordered = float(totals.get("total_ordered") or 0)
        received = float(totals.get("total_received") or 0)

        def _rate(numerator: float, denominator: float) -> float | None:
            return round(numerator / denominator, 4) if denominator > 0 else None

        by_month = self.client.fetch_all(
            "SELECT DATE_FORMAT(COALESCE(po.ORDERDATE, po.STARTDATE), '%%Y-%%m') AS MONTH, "
            "COALESCE(SUM(p.ORDERQTY), 0) AS ordered_qty, "
            "COALESCE(SUM(CASE WHEN COALESCE(r.received_qty, 0) < 0 THEN 0 ELSE COALESCE(r.received_qty, 0) END), 0) AS received_qty "
            f"FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID {_RECEIVED_AGG} "
            f"WHERE {where} GROUP BY MONTH ORDER BY MONTH DESC",
            params, limit=24,
        )
        by_supplier = self.client.fetch_all(
            "SELECT COALESCE(NULLIF(po.VENDOR, ''), '未填供应商') AS VENDOR, "
            "COALESCE(SUM(p.ORDERQTY), 0) AS ordered_qty, "
            "COALESCE(SUM(CASE WHEN COALESCE(r.received_qty, 0) < 0 THEN 0 ELSE COALESCE(r.received_qty, 0) END), 0) AS received_qty "
            f"FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID {_RECEIVED_AGG} "
            f"WHERE {where} GROUP BY VENDOR ORDER BY ordered_qty DESC",
            params, limit=20,
        )
        by_item = self.client.fetch_all(
            "SELECT p.ITEMNUM, "
            "COALESCE(SUM(p.ORDERQTY), 0) AS ordered_qty, "
            "COALESCE(SUM(CASE WHEN COALESCE(r.received_qty, 0) < 0 THEN 0 ELSE COALESCE(r.received_qty, 0) END), 0) AS received_qty "
            f"FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID {_RECEIVED_AGG} "
            f"WHERE {where} GROUP BY p.ITEMNUM ORDER BY ordered_qty DESC",
            params, limit=20,
        )

        def _with_rate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for row in rows:
                row_ordered = float(row.get("ordered_qty") or 0)
                row_received = float(row.get("received_qty") or 0)
                out.append({**row, "rate": _rate(row_received, row_ordered)})
            return out

        return {
            "itemnum": itemnum,
            "supplier": supplier,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "window_applied": window_applied,
            "contract_lines": int(totals.get("contract_lines") or 0),
            "total_ordered": round(ordered, 2),
            "total_received": round(received, 2),
            "overall_rate": _rate(received, ordered),
            "by_month": _with_rate(by_month),
            "by_supplier": _with_rate(by_supplier),
            "by_item": _with_rate(by_item),
            "formula_explanation": "到货率 = 已入库数量 / 合同数量（数量口径，仅统计有效合同；入库按 matrectrans 接收流水核销，退库负数冲减）",
        }

    def lead_time(self, itemnum: str | None = None, supplier: str | None = None) -> dict[str, Any] | None:
        """实测供应交期（月）= 首次入库日期 − 合同下单日期，按维度聚合。

        口径说明（实测）：
        - 入库流水（matrectrans）与 poline 的行级匹配率为 0，与 po 的 PONUM 匹配率 99.8%，
          且入库多记在 PDSITE、合同在 PHP，因此只按 PONUM 关联 po，不带 SITEID；
        - 仅统计首次入库不早于下单日期的样本（99.99% 样本满足）。
        回退顺序：物资 → 供应商 → 全厂实测均值 → None（调用方用配置默认值）。
        """
        receipt_filters = ["ISSUETYPE = 'RECEIPT'", "ACTUALDATE IS NOT NULL", "PONUM IS NOT NULL", "PONUM <> ''"]
        receipt_params: list[Any] = []
        if itemnum:
            receipt_filters.append("ITEMNUM = %s")
            receipt_params.append(itemnum)
        first_receipt = (
            "JOIN (SELECT PONUM, MIN(ACTUALDATE) AS first_receipt FROM matrectrans "
            f"WHERE {' AND '.join(receipt_filters)} GROUP BY PONUM) r ON r.PONUM = m.PONUM"
        )
        valid_po = (
            f"po.ORDERDATE IS NOT NULL AND po.STATUS NOT IN ({','.join(_VALID_PO_EXCLUDE)}) "
        )

        def _query(group_expr: str, extra_where: str, params: list[Any]) -> dict[str, Any] | None:
            rows = self.client.fetch_all(
                "SELECT " + group_expr + " AS GROUP_KEY, "
                "AVG(DATEDIFF(r.first_receipt, po.ORDERDATE)) / 30.4 AS lead_months, "
                "MIN(DATEDIFF(r.first_receipt, po.ORDERDATE)) AS min_days, "
                "MAX(DATEDIFF(r.first_receipt, po.ORDERDATE)) AS max_days, "
                "COUNT(*) AS samples "
                "FROM matrectrans m "
                f"JOIN po ON po.PONUM = m.PONUM {first_receipt} "
                "WHERE m.ISSUETYPE = 'RECEIPT' AND " + valid_po +
                " AND r.first_receipt >= po.ORDERDATE" + extra_where +
                " GROUP BY GROUP_KEY ORDER BY samples DESC LIMIT 1",
                params, limit=1,
            )
            if not rows:
                return None
            row = rows[0]
            return {
                "group_key": str(row.get("GROUP_KEY")),
                "lead_months": round(float(row.get("lead_months") or 0), 2),
                "min_days": int(row.get("min_days") or 0),
                "max_days": int(row.get("max_days") or 0),
                "samples": int(row.get("samples") or 0),
            }

        if itemnum:
            hit = _query("m.ITEMNUM", " AND m.ITEMNUM = %s", [*receipt_params, itemnum])
            if hit:
                return {**hit, "dimension": "item"}
            vendor_rows = self.client.fetch_all(
                "SELECT po.VENDOR FROM matrectrans m JOIN po ON po.PONUM = m.PONUM "
                "WHERE m.ISSUETYPE = 'RECEIPT' AND m.ITEMNUM = %s AND " + valid_po +
                " AND COALESCE(NULLIF(po.VENDOR, ''), '') <> '' ORDER BY m.ACTUALDATE DESC",
                [itemnum], limit=1,
            )
            if vendor_rows and vendor_rows[0].get("VENDOR"):
                vendor = vendor_rows[0]["VENDOR"]
                hit = _query("po.VENDOR", " AND po.VENDOR = %s", [*receipt_params, vendor])
                if hit:
                    return {**hit, "dimension": "supplier", "via_item": itemnum}
        if supplier:
            hit = _query("po.VENDOR", " AND po.VENDOR LIKE %s",
                         [*receipt_params, f"%{self._escape_like(supplier)}%"])
            if hit:
                return {**hit, "dimension": "supplier"}
        # 兜底：全厂实测均值（仍为实测值，优于配置默认）
        site_hit = self._site_lead_time()
        if site_hit:
            return {**site_hit, "dimension": "site"}
        return None

    def _site_lead_time(self) -> dict[str, Any] | None:
        """全厂实测交期均值（复用主流程的关联口径，无额外过滤）。"""
        rows = self.client.fetch_all(
            "SELECT AVG(DATEDIFF(r.first_receipt, po.ORDERDATE)) / 30.4 AS lead_months, "
            "MIN(DATEDIFF(r.first_receipt, po.ORDERDATE)) AS min_days, "
            "MAX(DATEDIFF(r.first_receipt, po.ORDERDATE)) AS max_days, COUNT(*) AS samples "
            "FROM matrectrans m "
            "JOIN po ON po.PONUM = m.PONUM "
            "JOIN (SELECT PONUM, MIN(ACTUALDATE) AS first_receipt FROM matrectrans "
            "WHERE ISSUETYPE = 'RECEIPT' AND ACTUALDATE IS NOT NULL AND PONUM IS NOT NULL AND PONUM <> '' "
            "GROUP BY PONUM) r ON r.PONUM = m.PONUM "
            "WHERE m.ISSUETYPE = 'RECEIPT' AND " + f"po.ORDERDATE IS NOT NULL AND po.STATUS NOT IN ({','.join(_VALID_PO_EXCLUDE)}) " +
            "AND r.first_receipt >= po.ORDERDATE LIMIT 1",
            [], limit=1,
        )
        if not rows or not rows[0].get("samples"):
            return None
        row = rows[0]
        return {
            "group_key": get_settings().erp_site_id,
            "lead_months": round(float(row.get("lead_months") or 0), 2),
            "min_days": int(row.get("min_days") or 0),
            "max_days": int(row.get("max_days") or 0),
            "samples": int(row.get("samples") or 0),
        }

    # ---------- 搜索联想 ----------

    # 联想索引：字段 → item 表表达式（itemnum/description/model 有对应数据来源）
    SUGGEST_FIELDS = {
        "itemnum": "i.ITEMNUM LIKE %s",
        "description": "i.DESCRIPTION LIKE %s",
        "model": "i.HDMODEL LIKE %s",
    }

    @staticmethod
    def _escape_like(keyword: str) -> str:
        """转义 LIKE 通配符，防止用户输入 %/_ 摊大结果集。"""
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def suggest_items(self, keyword: str, field: str = "itemnum", site_id: str | None = None,
                      limit: int = 20) -> list[dict]:
        """物资联想（采购建议同款交互的后端）：按 编码/名称/规格 联想，附带库存标记。

        关键词为空 → 返回默认浏览列表（有库存优先，按编码排序），下拉一聚焦即出选项。
        item.ITEMNUM 有索引（idx_itemnum）；description/model 为全表过滤（约 4 万行，LIMIT 内可接受）。
        """
        if keyword.strip():
            field_expr = self.SUGGEST_FIELDS.get(field)
            if field_expr is None:
                raise ErpQueryError(f"不支持的联想字段: {field}")
            like = f"%{self._escape_like(keyword.strip())}%"
            where, params = field_expr, [like]
        else:
            # 浏览模式：与索引无关，优先展示有库存的物资
            where = ("EXISTS(SELECT 1 FROM invbalances b WHERE b.ITEMNUM = i.ITEMNUM AND b.CURBAL > 0)")
            params = []
        settings = get_settings()
        site_id = site_id or settings.erp_site_id
        rows = self.client.fetch_all(
            "SELECT i.ITEMNUM, i.DESCRIPTION, COALESCE(NULLIF(i.HDMODEL, ''), '') AS HDMODEL, "
            "COALESCE(NULLIF(i.ISSUEUNIT, '个'), '个') AS ISSUEUNIT, "
            "EXISTS(SELECT 1 FROM invbalances b WHERE b.ITEMNUM = i.ITEMNUM AND b.CURBAL > 0) AS has_stock "
            "FROM item i WHERE i.STATUS = 'ACTIVE' AND " + where +
            " ORDER BY i.ITEMNUM",
            params,
            limit=limit * 4,
        )
        if not keyword.strip():
            return rows[:limit]
        # 排序：精确 > 前缀 > 包含；有库存优先
        kw = keyword.strip().upper()

        def rank(r: dict) -> tuple:
            num = str(r.get("ITEMNUM") or "").upper()
            desc = str(r.get("DESCRIPTION") or "").upper()
            exact = 0 if kw in (num, desc) else (1 if num.startswith(kw) or desc.startswith(kw) else 2)
            return (exact, 0 if r.get("has_stock") else 1, num)

        rows.sort(key=rank)
        return rows[:limit]

    # ---------- 汇总分析 ----------

    def balance_analysis(self, itemnum: str, site_id: str | None = None, prnum: str | None = None, prlinenum: int | None = None, request_qty: float | None = None) -> dict[str, Any]:
        site_id = site_id or get_settings().erp_site_id
        item = self.item_info(itemnum, site_id)

        pr_line: dict[str, Any] | None = None
        if prnum:
            sql = "SELECT PRNUM, PRLINENUM, ITEMNUM, DESCRIPTION, ORDERQTY, ORDERUNIT, ENTERDATE, REQUESTEDBY FROM prline WHERE PRNUM = %s AND SITEID = %s"
            params: list[Any] = [prnum, site_id]
            if itemnum:
                sql += " AND ITEMNUM = %s"
                params.append(itemnum)
            if prlinenum is not None:
                sql += " AND PRLINENUM = %s"
                params.append(prlinenum)
            sql += " ORDER BY ENTERDATE DESC"
            rows = self.client.fetch_all(sql, params, limit=1)
            if rows:
                pr_line = dict(rows[0])
        if request_qty is None and pr_line:
            request_qty = float(pr_line.get("ORDERQTY") or 0)

        history = self.history_purchase(itemnum, site_id)
        transit = self.in_transit(itemnum, site_id)
        usage = self.work_order_usage(itemnum, site_id)
        stock = self.stock_balance(itemnum, site_id)
        reserve = self.reservations(itemnum, site_id)
        receipts = self.receipt_history(itemnum, site_id)

        safety_stock = float(item.get("safety_stock") or 0)
        stock_qty = stock["total_qty"]
        reserved_qty = reserve["total_qty"]
        in_transit_qty = transit["in_transit_qty"]
        # 可用量 = 库存量 + 在途量 - 预留量
        available_qty = stock_qty + in_transit_qty - reserved_qty
        demand = float(request_qty or 0)
        if demand <= 0:
            conclusion = "no_request"
            suggestion_qty = max(available_qty < safety_stock and (safety_stock - available_qty) or 0, 0)
            conclusion_text = "未关联立项申请行或申请数量为 0，仅展示库存状况；如可用量低于安全库存，建议按缺口补库。"
        elif available_qty >= demand:
            conclusion = "satisfied"
            suggestion_qty = 0.0
            conclusion_text = f"可用量 {round(available_qty, 2)} 可满足本次申请 {round(demand, 2)}，无需采购，建议平衡利库（领用/调拨）。"
        elif available_qty > 0:
            conclusion = "partial"
            suggestion_qty = max(demand - available_qty, 0)
            conclusion_text = f"可用量 {round(available_qty, 2)} 仅能满足部分申请（{round(available_qty / demand * 100, 1)}%），建议采购 {round(suggestion_qty, 2)}。"
        else:
            conclusion = "purchase"
            suggestion_qty = max(demand - available_qty, 0)
            conclusion_text = f"可用量不足（{round(available_qty, 2)}），需按申请量采购 {round(demand, 2)}。"
        # 叠加安全库存的参考采购量（不影响结论）
        suggestion_with_safety = max(demand + safety_stock - available_qty, 0)

        return {
            "site_id": site_id,
            "pr_line": pr_line,
            "request_qty": demand,
            "item": {k: v for k, v in item.items() if k != "inventory_records"},
            "dimensions": {
                "history_purchase": history,
                "in_transit": transit,
                "work_order_usage": usage,
                "stock_balance": stock,
                "reservations": reserve,
                "safety_stock": {"total_qty": safety_stock, "details": item.get("inventory_records", [])},
                "receipt_history": receipts,
            },
            "summary": {
                "history_purchase_qty": history["total_qty"],
                "in_transit_qty": in_transit_qty,
                "work_order_issued_qty": usage["issued_qty"],
                "work_order_planned_qty": usage["planned_qty"],
                "work_order_returned_qty": usage["returned_qty"],
                "stock_qty": stock_qty,
                "reserved_qty": reserved_qty,
                "safety_stock_qty": safety_stock,
                "available_qty": available_qty,
            },
            "conclusion": {
                "status": conclusion,
                "text": conclusion_text,
                "suggested_purchase_qty": round(suggestion_qty, 2),
                "suggested_purchase_with_safety": round(suggestion_with_safety, 2),
            },
            "formula_explanation": {
                "available": "可用量 = 库存量 + 在途量 - 预留量",
                "in_transit": "在途量 = 合同数量 - 入库数量（未关闭有效合同）",
                "suggestion": "建议采购量 = 申请数量 - 可用量（参考值再叠加安全库存）",
                "safety": "安全库存 = 主库存项目（inventory）最低库存 MINLEVEL",
            },
        }
