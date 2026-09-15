"""Import the read-only Jimu/Maximo ERP dataset into agent's local business DB."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.erp.client import ErpClient
from app.exceptions import BusinessError
from app.models import (
    Alert, ForecastRecord, InventorySnapshot, Material, PriceRecord,
    ProcurementOrder, PurchaseRecommendationRecord, SafetyStockRule,
    StockMovement, Supplier, TransferRoute, UsageRecord, WarningRule,
    Warehouse,
)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class ErpImportService:
    """ERP extractor aligned with agent2's JimuAdapter field mapping."""

    def __init__(self, client: ErpClient | None = None) -> None:
        self.client = client or ErpClient()

    def _fetch(self) -> dict[str, list[dict[str, Any]]]:
        site = get_settings().erp_site_id
        warehouses = self.client.fetch_all(
            "SELECT LOCATION, DESCRIPTION FROM locations WHERE SITEID = %s ORDER BY LOCATION",
            [site], limit=1_000,
        )
        materials = self.client.fetch_all(
            "SELECT ITEMNUM, DESCRIPTION, HDMODEL, ISSUEUNIT, HDMCLASS "
            "FROM item WHERE STATUS = 'ACTIVE' ORDER BY ITEMNUM",
            limit=100_000,
        )
        inventory = self.client.fetch_all(
            "SELECT b.ITEMNUM, b.LOCATION, b.AVAILABLE_QTY, COALESCE(r.UNIT_COST, 0) AS UNIT_COST "
            "FROM (SELECT ITEMNUM, LOCATION, SUM(COALESCE(CURBAL, 0)) AS AVAILABLE_QTY "
            "      FROM invbalances WHERE SITEID = %s AND COALESCE(IS_DEL, 0) = 0 "
            "      GROUP BY ITEMNUM, LOCATION) b "
            "LEFT JOIN (SELECT ITEMNUM, STORELOC, MAX(COALESCE(UNITCOST, 0)) AS UNIT_COST "
            "           FROM matrectrans WHERE SITEID = %s AND ISSUETYPE = 'RECEIPT' "
            "           GROUP BY ITEMNUM, STORELOC) r "
            "ON r.ITEMNUM = b.ITEMNUM AND r.STORELOC = b.LOCATION",
            [site, site], limit=100_000,
        )
        procurement = self.client.fetch_all(
            "SELECT p.PONUM, p.POLINENUM, p.ITEMNUM, p.ORDERQTY, p.UNITCOST, "
            "po.VENDOR, po.STARTDATE "
            "FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID "
            "WHERE po.SITEID = %s AND p.ITEMNUM IS NOT NULL AND po.STARTDATE IS NOT NULL "
            "AND po.STATUS NOT IN ('WAPPR', 'CAN')",
            [site], limit=100_000,
        )
        usage = self.client.fetch_all(
            "SELECT MATUSETRANSID, ITEMNUM, STORELOC, QUANTITY, ACTUALDATE, REFWO "
            "FROM matusetrans WHERE SITEID = %s AND ISSUETYPE = 'ISSUE' "
            "AND ITEMNUM IS NOT NULL AND STORELOC IS NOT NULL AND ACTUALDATE IS NOT NULL",
            [site], limit=100_000,
        )
        receipts = self.client.fetch_all(
            "SELECT MATRECTRANSID, ITEMNUM, STORELOC, QUANTITY, UNITCOST, ACTUALDATE, PONUM, ISSUETYPE "
            "FROM matrectrans WHERE SITEID = %s AND ISSUETYPE IN ('RECEIPT', 'RETURN') "
            "AND ITEMNUM IS NOT NULL AND STORELOC IS NOT NULL AND ACTUALDATE IS NOT NULL",
            [site], limit=100_000,
        )
        return {
            "warehouses": warehouses, "materials": materials, "inventory": inventory,
            "procurement": procurement, "usage": usage, "receipts": receipts,
        }

    async def replace_with_erp_data(self, session: AsyncSession) -> dict[str, int]:
        # Do every external read before clearing local records.
        source = await asyncio.to_thread(self._fetch)
        if not source["warehouses"] or not source["materials"] or not source["inventory"]:
            raise BusinessError(code="ERP_IMPORT_INCOMPLETE", message="ERP 返回的库房、物料或库存为空，已取消导入且未清理本地数据")

        material_by_sku = {str(row["ITEMNUM"]): row for row in source["materials"]}
        warehouse_ids = {str(row["LOCATION"]) for row in source["warehouses"]}

        # Remove generated/demo business data. Authentication settings are intentionally preserved.
        for model in (Alert, ForecastRecord, PurchaseRecommendationRecord, TransferRoute,
                      WarningRule, SafetyStockRule, StockMovement, PriceRecord,
                      UsageRecord, ProcurementOrder, InventorySnapshot, Supplier,
                      Material, Warehouse):
            await session.execute(delete(model))

        session.add_all([
            Warehouse(warehouse_id=str(row["LOCATION"]), name=str(row.get("DESCRIPTION") or row["LOCATION"]),
                      organization_id=get_settings().erp_site_id)
            for row in source["warehouses"] if row.get("LOCATION")
        ])
        session.add_all([
            Material(
                sku=sku,
                name=str(row.get("DESCRIPTION") or sku)[:160],
                category=str(row.get("HDMCLASS") or "未分类")[:80],
                unit=str(row.get("ISSUEUNIT") or "个")[:20],
                package_size=Decimal("1"),
            )
            for sku, row in material_by_sku.items()
        ])
        session.add_all([
            InventorySnapshot(
                sku=str(row["ITEMNUM"]), warehouse_id=str(row["LOCATION"]),
                available_quantity=_decimal(row.get("AVAILABLE_QTY")),
                in_transit_quantity=Decimal("0"), unit_cost=_decimal(row.get("UNIT_COST")),
            )
            for row in source["inventory"]
            if str(row.get("ITEMNUM")) in material_by_sku and str(row.get("LOCATION")) in warehouse_ids
        ])

        supplier_names = {str(row.get("VENDOR") or "ERP供应商") for row in source["procurement"]}
        session.add_all([Supplier(supplier_code=f"ERP-{index:05d}", name=name[:160])
                         for index, name in enumerate(sorted(supplier_names), 1)])
        session.add_all([
            ProcurementOrder(
                sku=str(row["ITEMNUM"]), warehouse_id="ERP", supplier=str(row.get("VENDOR") or "ERP供应商")[:160],
                quantity=_decimal(row.get("ORDERQTY")), unit_price=_decimal(row.get("UNITCOST")),
                ordered_at=_date(row["STARTDATE"]),
            )
            for row in source["procurement"] if str(row.get("ITEMNUM")) in material_by_sku
        ])
        session.add_all([
            UsageRecord(
                sku=str(row["ITEMNUM"]), warehouse_id=str(row["STORELOC"]),
                quantity=abs(_decimal(row.get("QUANTITY"))), used_at=_date(row["ACTUALDATE"]),
                work_order_id=str(row.get("REFWO") or row.get("MATUSETRANSID") or "")[:80] or None,
            )
            for row in source["usage"]
            if str(row.get("ITEMNUM")) in material_by_sku and str(row.get("STORELOC")) in warehouse_ids
        ])
        session.add_all([
            PriceRecord(
                sku=str(row["ITEMNUM"]), supplier=str(row.get("VENDOR") or "ERP供应商")[:160],
                price=_decimal(row.get("UNITCOST")), recorded_at=_date(row["STARTDATE"]),
            )
            for row in source["procurement"]
            if str(row.get("ITEMNUM")) in material_by_sku and row.get("UNITCOST") is not None
        ])
        session.add_all([
            StockMovement(
                sku=str(row["ITEMNUM"]), warehouse_id=str(row["STORELOC"]),
                movement_type="receipt" if row.get("ISSUETYPE") == "RECEIPT" else "purchase_return",
                quantity=_decimal(row.get("QUANTITY")), unit=str(material_by_sku[str(row["ITEMNUM"])].get("ISSUEUNIT") or "个")[:20],
                posting_date=_date(row["ACTUALDATE"]), reference_no=str(row.get("PONUM") or row.get("MATRECTRANSID") or "")[:120] or None,
            )
            for row in source["receipts"]
            if str(row.get("ITEMNUM")) in material_by_sku and str(row.get("STORELOC")) in warehouse_ids
        ])
        session.add_all([
            StockMovement(
                sku=str(row["ITEMNUM"]), warehouse_id=str(row["STORELOC"]), movement_type="issue",
                quantity=abs(_decimal(row.get("QUANTITY"))), unit=str(material_by_sku[str(row["ITEMNUM"])].get("ISSUEUNIT") or "个")[:20],
                posting_date=_date(row["ACTUALDATE"]), reference_no=str(row.get("REFWO") or row.get("MATUSETRANSID") or "")[:120] or None,
            )
            for row in source["usage"]
            if str(row.get("ITEMNUM")) in material_by_sku and str(row.get("STORELOC")) in warehouse_ids
        ])
        await session.commit()
        return {key: len(value) for key, value in source.items()}
