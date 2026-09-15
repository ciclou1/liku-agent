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

from typing import Any

from app.core.config import get_settings
from app.erp.client import ErpClient, ErpQueryError

# 视为有效合同的 po.STATUS（排除未批准与已取消）
_VALID_PO_EXCLUDE = ("'WAPPR'", "'CAN'")
_OPEN_PO_EXCLUDE = ("'CLOSE'", "'CAN'", "'CLOSED'", "'WAPPR'")


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
