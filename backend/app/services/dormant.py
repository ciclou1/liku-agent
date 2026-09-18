"""呆滞库存识别服务：SQL 侧过滤 + 页内信号补全，处置判定走 algorithms/dormant.py。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.dormant import classify_disposal
from app.models import InventorySnapshot, Material, PriceRecord, ProcurementOrder, StockMovement, UsageRecord, Warehouse


class DormantService:
    async def list_dormant(
        self, session: AsyncSession, threshold_days: int = 365,
        warehouse_id: str | None = None, page: int = 1, size: int = 50,
    ) -> dict:
        """呆滞清单：可用量 > 0 且超过阈值无领用（含从未领用），按金额降序分页。

        调剂/退货信号只对当前页行批量补全，避免 4 万物资全量计算。
        """
        today = date.today()
        cutoff = today - timedelta(days=threshold_days)
        purchase_cutoff = today - timedelta(days=365)

        base_conditions = [
            InventorySnapshot.available_quantity > 0,
            (InventorySnapshot.last_used_at.is_(None)) | (InventorySnapshot.last_used_at <= cutoff),
        ]
        if warehouse_id:
            base_conditions.append(InventorySnapshot.warehouse_id == warehouse_id)

        total = int(await session.scalar(
            select(func.count()).select_from(InventorySnapshot).where(*base_conditions)) or 0)

        rows = (await session.execute(
            select(InventorySnapshot, Material.name, Material.unit)
            .outerjoin(Material, Material.sku == InventorySnapshot.sku)
            .where(*base_conditions)
            .order_by((InventorySnapshot.available_quantity * InventorySnapshot.unit_cost).desc(),
                      InventorySnapshot.sku)
            .offset((max(1, page) - 1) * size).limit(size))).all()

        page_skus = {row[0].sku for row in rows}
        # 调剂信号：其他仓库近 12 个月有领用，且现存量低于需求
        # （安全库存；ERP 未设 MINLEVEL 时用该仓年领用量，避免 safety=0 永远无缺口）
        transfer_demand: dict[str, list[str]] = {}
        if page_skus:
            usage_qty_rows = await session.execute(
                select(UsageRecord.sku, UsageRecord.warehouse_id, func.sum(UsageRecord.quantity))
                .where(UsageRecord.sku.in_(page_skus),
                       UsageRecord.used_at >= purchase_cutoff)
                .group_by(UsageRecord.sku, UsageRecord.warehouse_id))
            usage_by_key = {(sku, wh): float(qty or 0) for sku, wh, qty in usage_qty_rows.all()}
            if usage_by_key:
                stock_rows = await session.execute(
                    select(InventorySnapshot.sku, InventorySnapshot.warehouse_id,
                           InventorySnapshot.available_quantity, InventorySnapshot.safety_stock)
                    .where(InventorySnapshot.sku.in_({sku for sku, _wh in usage_by_key})))
                stock_by_key = {(r.sku, r.warehouse_id): (float(r.available_quantity or 0), float(r.safety_stock or 0))
                                for r in stock_rows.all()}
                for (sku, wh), year_usage in usage_by_key.items():
                    available, safety = stock_by_key.get((sku, wh), (0.0, 0.0))
                    needed = safety if safety > 0 else year_usage
                    if year_usage > 0 and available < needed:
                        transfer_demand.setdefault(sku, []).append(wh)
        # 退货信号：近 12 个月入库流水 → 采购合同 → 价格记录（合同表为空时仍能命中入库）
        last_purchases: dict[str, dict] = {}
        if page_skus:
            receipt_rows = await session.execute(
                select(StockMovement.sku,
                       func.max(StockMovement.posting_date).label("last_date"),
                       func.max(StockMovement.reference_no).label("reference"))
                .where(StockMovement.sku.in_(page_skus),
                       StockMovement.movement_type == "receipt",
                       StockMovement.posting_date >= purchase_cutoff)
                .group_by(StockMovement.sku))
            for sku, last_date, reference in receipt_rows.all():
                if last_date:
                    last_purchases[sku] = {"date": str(last_date), "supplier": reference or "供应商"}
            purchase_rows = await session.execute(
                select(ProcurementOrder.sku,
                       func.max(ProcurementOrder.ordered_at).label("last_date"),
                       func.max(ProcurementOrder.supplier).label("supplier"))
                .where(ProcurementOrder.sku.in_(page_skus),
                       ProcurementOrder.ordered_at >= purchase_cutoff)
                .group_by(ProcurementOrder.sku))
            for sku, last_date, supplier in purchase_rows.all():
                if sku not in last_purchases and last_date:
                    last_purchases[sku] = {"date": str(last_date), "supplier": supplier or "供应商"}
            if len(last_purchases) < len(page_skus):
                price_rows = await session.execute(
                    select(PriceRecord.sku,
                           func.max(PriceRecord.recorded_at).label("last_date"),
                           func.max(PriceRecord.supplier).label("supplier"))
                    .where(PriceRecord.sku.in_(page_skus),
                           PriceRecord.recorded_at >= purchase_cutoff)
                    .group_by(PriceRecord.sku))
                for sku, last_date, supplier in price_rows.all():
                    if sku not in last_purchases and last_date:
                        last_purchases[sku] = {"date": str(last_date), "supplier": supplier or "供应商"}
        warehouse_names = {row.warehouse_id: row.name for row in
                           (await session.execute(select(Warehouse))).scalars().all()}

        items = []
        for snapshot, name, unit in rows:
            material_name = name or snapshot.sku
            demand_whs = [wh for wh in transfer_demand.get(snapshot.sku, []) if wh != snapshot.warehouse_id]
            result = classify_disposal({
                "sku": snapshot.sku,
                "warehouse_id": snapshot.warehouse_id,
                "available_quantity": float(snapshot.available_quantity or 0),
                "unit_cost": float(snapshot.unit_cost or 0),
                "last_used_at": snapshot.last_used_at,
                "has_transfer_demand": bool(demand_whs),
                "demand_warehouse": "、".join(warehouse_names.get(wh, wh) for wh in demand_whs[:3]) if demand_whs else None,
                "last_purchase": last_purchases.get(snapshot.sku),
            }, today)
            items.append({
                "sku": snapshot.sku, "name": material_name, "unit": unit or "个",
                "warehouse_id": snapshot.warehouse_id,
                "warehouse_name": warehouse_names.get(snapshot.warehouse_id, snapshot.warehouse_id),
                "available_quantity": float(snapshot.available_quantity or 0),
                "unit_cost": float(snapshot.unit_cost or 0),
                "last_used_at": str(snapshot.last_used_at) if snapshot.last_used_at else None,
                "amount": result.amount, "days_idle": result.days_idle,
                "suggestion": result.suggestion, "action": result.action, "basis": result.basis,
            })

        summary = {
            "transfer": sum(1 for item in items if item["suggestion"] == "调剂"),
            "return": sum(1 for item in items if item["suggestion"] == "退货"),
            "scrap": sum(1 for item in items if item["suggestion"] == "报废评估"),
        }
        return {
            "items": items, "total": total, "page": max(1, page), "size": size,
            "threshold_days": threshold_days,
            "page_amount": round(sum(item["amount"] for item in items), 2),
            "summary": summary,
        }
