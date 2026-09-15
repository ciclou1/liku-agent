from datetime import date
from math import ceil, cos, radians, sin, sqrt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventorySnapshot, Material, PriceRecord, SafetyStockRule, UsageRecord, WarningRule, Warehouse
from app.models.operations import TransferRoute


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _number(value: Decimal | None) -> float:
    return float(value or 0)


class DomainRepository:
    async def materials(self, session: AsyncSession, query: str | None = None, limit: int | None = None) -> list[dict]:
        statement = select(Material).order_by(Material.sku)
        if query:
            like = f"%{query}%"
            statement = statement.where(Material.sku.ilike(like) | Material.name.ilike(like))
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await session.execute(statement)).scalars().all()
        return [{"sku": row.sku, "name": row.name, "category": row.category, "unit": row.unit, "package_size": _number(row.package_size), "shelf_life_days": row.shelf_life_days} for row in rows]

    async def inventory(self, session: AsyncSession, query: str | None = None, warehouse_id: str | None = None,
                       limit: int | None = None, offset: int = 0) -> list[dict]:
        statement = select(InventorySnapshot)
        if warehouse_id:
            statement = statement.where(InventorySnapshot.warehouse_id == warehouse_id)
        if query:
            statement = statement.where(InventorySnapshot.sku.ilike(f"%{query}%"))
        statement = statement.order_by(InventorySnapshot.sku, InventorySnapshot.warehouse_id)
        if limit is not None:
            statement = statement.offset(offset).limit(limit)
        rows = (await session.execute(statement)).scalars().all()
        materials = {row.sku: row for row in (await session.execute(select(Material))).scalars().all()}
        warehouses = {row.warehouse_id: row.name for row in (await session.execute(select(Warehouse))).scalars().all()}
        safety = {row.category: _number(row.quantity) for row in (await session.execute(select(SafetyStockRule))).scalars().all()}
        result = []
        for row in rows:
            material = materials.get(row.sku)
            # per-SKU 安全库存（ERP 主库存项目 MINLEVEL）优先；未设置时回退分类规则
            sku_safety = _number(getattr(row, "safety_stock", 0))
            category_safety = safety.get(material.category, 0) if material else 0
            item = self._inventory_row(row, material.name if material else row.sku, sku_safety or category_safety, warehouses.get(row.warehouse_id))
            if not query or query.lower() in row.sku.lower() or query.lower() in item["name"].lower():
                result.append(item)
        return result

    async def usage(self, session: AsyncSession, sku: str, warehouse_id: str) -> list[dict]:
        rows = (await session.execute(select(UsageRecord).where(UsageRecord.sku == sku, UsageRecord.warehouse_id == warehouse_id).order_by(UsageRecord.used_at))).scalars().all()
        material = await session.scalar(select(Material).where(Material.sku == sku))
        category = material.category if material else "未分类"
        return [{"period": row.used_at.strftime("%Y-%m"), "usage": _number(row.quantity), "procurement": 0, "month": row.used_at.month, "maintenance_count": 0, "category": category} for row in rows]

    async def prices(self, session: AsyncSession, sku: str) -> list[dict]:
        rows = (await session.execute(select(PriceRecord).where(PriceRecord.sku == sku).order_by(PriceRecord.recorded_at))).scalars().all()
        return [{"sku": row.sku, "supplier": row.supplier, "price": _number(row.price), "recorded_at": row.recorded_at.isoformat()} for row in rows]

    async def warning_rules(self, session: AsyncSession) -> list[WarningRule]:
        return list((await session.execute(select(WarningRule).where(WarningRule.enabled.is_(True)))).scalars().all())

    async def routes(self, session: AsyncSession) -> dict[tuple[str, str], tuple[float, int]]:
        rows = (await session.execute(select(TransferRoute))).scalars().all()
        routes = {(row.source_warehouse_id, row.target_warehouse_id): (_number(row.distance_km), row.lead_time_days) for row in rows}
        warehouses = (await session.execute(select(Warehouse))).scalars().all()
        locations = {row.warehouse_id: (float(row.latitude), float(row.longitude)) for row in warehouses if row.latitude is not None and row.longitude is not None}
        inventory_warehouse_ids = set((await session.execute(select(InventorySnapshot.warehouse_id))).scalars().all())
        warehouse_ids = inventory_warehouse_ids | set(locations)
        for source_id, target_id in routes:
            warehouse_ids.update((source_id, target_id))
        # Estimate an undirected road route when the ERP has no explicit lane.
        # This keeps the recommendation actionable while the customer route table is being integrated.
        for source_id in warehouse_ids:
            for target_id in warehouse_ids:
                if source_id == target_id or ((source_id, target_id) in routes and routes[(source_id, target_id)][0] > 0 and routes[(source_id, target_id)][1] > 0):
                    continue
                source = locations.get(source_id)
                target = locations.get(target_id)
                if source and target:
                    lat1, lon1 = map(radians, source)
                    lat2, lon2 = map(radians, target)
                    haversine_km = 6371.0 * 2 * asin_safe(sqrt(sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((radians(target[1]) - radians(source[1])) / 2) ** 2))
                    road_km = round(max(1.0, haversine_km * 1.2), 1)
                else:
                    # Fallback for legacy ERP rows without warehouse coordinates.
                    # It is deliberately non-zero and conservative until route data is integrated.
                    source_number = int(source_id.removeprefix("W")) if source_id.removeprefix("W").isdigit() else 1
                    target_number = int(target_id.removeprefix("W")) if target_id.removeprefix("W").isdigit() else 1
                    road_km = float(max(12, abs(source_number - target_number) * 120))
                routes[(source_id, target_id)] = (road_km, max(1, ceil(road_km / 500)))
        return routes

    @staticmethod
    def _inventory_row(row: InventorySnapshot, name: str | None = None, safety_stock: float = 0, warehouse_name: str | None = None) -> dict:
        return {"sku": row.sku, "name": name or row.sku, "warehouse_id": row.warehouse_id, "warehouse_name": warehouse_name or row.warehouse_id, "available_quantity": _number(row.available_quantity), "in_transit": _number(row.in_transit_quantity), "unit_cost": _number(row.unit_cost), "safety_stock": safety_stock, "last_used_at": _date(row.last_used_at), "expiry_date": _date(row.expiry_date)}


def asin_safe(value: float) -> float:
    from math import asin

    return asin(max(-1.0, min(1.0, value)))
