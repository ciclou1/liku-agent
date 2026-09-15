from datetime import date, timedelta
from decimal import Decimal
from math import cos, pi, sin

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import engine
from app.models import Base, InventorySnapshot, Material, PriceRecord, ProcurementOrder, SafetyStockRule, StockMovement, Supplier, TransferRoute, UsageRecord, Warehouse, WarningRule


async def initialize_database() -> None:
    settings = get_settings()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        columns = await connection.run_sync(lambda sync_connection: {column["name"] for column in inspect(sync_connection).get_columns("purchase_recommendations")})
        if "warehouse_id" not in columns:
            await connection.execute(text("ALTER TABLE purchase_recommendations ADD COLUMN warehouse_id VARCHAR(80)"))
        # 轻量迁移：per-SKU 安全库存（ERP MINLEVEL）
        inv_columns = await connection.run_sync(lambda sync_connection: {column["name"] for column in inspect(sync_connection).get_columns("inventory_snapshots")})
        if "safety_stock" not in inv_columns:
            await connection.execute(text("ALTER TABLE inventory_snapshots ADD COLUMN safety_stock NUMERIC(18,4) NOT NULL DEFAULT 0"))
    if settings.demo_seed:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed_demo_data(session)


async def seed_demo_data(session: AsyncSession) -> None:
    existing = await session.scalar(select(Material.id).limit(1))
    if existing:
        await enrich_demo_data(session)
        return
    today = date.today()
    materials = [
        Material(sku="M12-BOLT", name="M12 螺栓", category="紧固件", unit="件", package_size=Decimal("10")),
        Material(sku="CABLE-10", name="10mm 电缆", category="电缆", unit="米", package_size=Decimal("50"), shelf_life_days=730),
        Material(sku="BEARING-6205", name="6205 深沟球轴承", category="轴承", unit="件", package_size=Decimal("4")),
        Material(sku="FILTER-A", name="液压油滤芯", category="滤芯", unit="件", package_size=Decimal("2"), shelf_life_days=1095),
        Material(sku="FUSE-10A", name="10A 保险丝", category="电气元件", unit="件", package_size=Decimal("20")),
    ]
    warehouses = [Warehouse(warehouse_id="W1", name="华东一号仓", organization_id="default", city="上海", latitude=Decimal("31.2304"), longitude=Decimal("121.4737")), Warehouse(warehouse_id="W2", name="华东二号仓", organization_id="default", city="苏州", latitude=Decimal("31.2989"), longitude=Decimal("120.5853")), Warehouse(warehouse_id="W3", name="华南备件仓", organization_id="default", city="广州", latitude=Decimal("23.1291"), longitude=Decimal("113.2644")), Warehouse(warehouse_id="W4", name="西南维修仓", organization_id="default", city="成都", latitude=Decimal("30.5728"), longitude=Decimal("104.0668"))]
    suppliers = [Supplier(supplier_code="SUP-001", name="华东工业品有限公司", contact_name="李工", lead_time_days=5), Supplier(supplier_code="SUP-002", name="远航电气供应链", contact_name="周工", lead_time_days=12), Supplier(supplier_code="SUP-003", name="精工轴承制造", contact_name="王工", lead_time_days=8)]
    inventory = [
        InventorySnapshot(sku="M12-BOLT", warehouse_id="W1", available_quantity=Decimal("120"), in_transit_quantity=Decimal("20"), unit_cost=Decimal("1.8"), last_used_at=today - timedelta(days=30)),
        InventorySnapshot(sku="M12-BOLT", warehouse_id="W2", available_quantity=Decimal("8"), in_transit_quantity=Decimal("0"), unit_cost=Decimal("1.8"), last_used_at=today - timedelta(days=15)),
        InventorySnapshot(sku="CABLE-10", warehouse_id="W3", available_quantity=Decimal("500"), in_transit_quantity=Decimal("0"), unit_cost=Decimal("28"), last_used_at=today - timedelta(days=450), expiry_date=today + timedelta(days=20)),
        InventorySnapshot(sku="BEARING-6205", warehouse_id="W1", available_quantity=Decimal("18"), in_transit_quantity=Decimal("8"), unit_cost=Decimal("36"), last_used_at=today - timedelta(days=210)),
        InventorySnapshot(sku="FILTER-A", warehouse_id="W4", available_quantity=Decimal("60"), in_transit_quantity=Decimal("0"), unit_cost=Decimal("86"), last_used_at=today - timedelta(days=520), expiry_date=today + timedelta(days=160)),
        InventorySnapshot(sku="FUSE-10A", warehouse_id="W2", available_quantity=Decimal("240"), in_transit_quantity=Decimal("100"), unit_cost=Decimal("2.6"), last_used_at=today - timedelta(days=40)),
    ]
    usage = [UsageRecord(sku="M12-BOLT", warehouse_id="W1", quantity=Decimal(str(value)), used_at=date(2026, index, 1), work_order_id=f"WO-{index}") for index, value in enumerate([40, 42, 38, 45, 41, 44], 1)]
    usage.extend([UsageRecord(sku="BEARING-6205", warehouse_id="W1", quantity=Decimal(str(value)), used_at=date(2026, index, 1), work_order_id=f"WO-B-{index}") for index, value in enumerate([5, 4, 6, 3, 5, 4], 1)])
    prices = [PriceRecord(sku="M12-BOLT", supplier=f"供应商-{index % 2 + 1}", price=Decimal(str(value)), recorded_at=date(2026, index + 1, 1)) for index, value in enumerate([1.7, 1.75, 1.8, 1.86])]
    prices.extend([PriceRecord(sku="CABLE-10", supplier="SUP-002", price=Decimal(str(value)), recorded_at=date(2026, index + 1, 1)) for index, value in enumerate([27.0, 27.8, 28.5, 29.2])])
    procurement = [ProcurementOrder(sku="M12-BOLT", warehouse_id="W1", supplier="SUP-001", quantity=Decimal("200"), unit_price=Decimal("1.7"), ordered_at=date(2026, 1, 12)), ProcurementOrder(sku="CABLE-10", warehouse_id="W3", supplier="SUP-002", quantity=Decimal("1000"), unit_price=Decimal("27"), ordered_at=date(2026, 2, 8)), ProcurementOrder(sku="BEARING-6205", warehouse_id="W1", supplier="SUP-003", quantity=Decimal("40"), unit_price=Decimal("35"), ordered_at=date(2026, 3, 18))]
    movements = [StockMovement(sku="M12-BOLT", warehouse_id="W1", movement_type="receipt", quantity=Decimal("200"), unit="件", posting_date=date(2026, 1, 15), reference_no="PO-2026-001"), StockMovement(sku="M12-BOLT", warehouse_id="W1", movement_type="issue", quantity=Decimal("40"), unit="件", posting_date=date(2026, 1, 28), reference_no="WO-1"), StockMovement(sku="CABLE-10", warehouse_id="W3", movement_type="receipt", quantity=Decimal("1000"), unit="米", posting_date=date(2026, 2, 20), reference_no="PO-2026-002"), StockMovement(sku="BEARING-6205", warehouse_id="W1", movement_type="receipt", quantity=Decimal("40"), unit="件", posting_date=date(2026, 3, 25), reference_no="PO-2026-003")]
    session.add_all(materials + warehouses + suppliers + inventory + usage + prices + procurement + movements + [TransferRoute(source_warehouse_id="W1", target_warehouse_id="W2", distance_km=Decimal("12"), lead_time_days=1, organization_id="default"), TransferRoute(source_warehouse_id="W3", target_warehouse_id="W2", distance_km=Decimal("18"), lead_time_days=2, organization_id="default"), TransferRoute(source_warehouse_id="W4", target_warehouse_id="W2", distance_km=Decimal("1650"), lead_time_days=5, organization_id="default"), SafetyStockRule(category="紧固件", quantity=Decimal("80"), service_level=Decimal("0.95")), SafetyStockRule(category="电缆", quantity=Decimal("120"), service_level=Decimal("0.95")), SafetyStockRule(category="轴承", quantity=Decimal("30"), service_level=Decimal("0.95")), SafetyStockRule(category="滤芯", quantity=Decimal("20"), service_level=Decimal("0.95")), SafetyStockRule(category="电气元件", quantity=Decimal("100"), service_level=Decimal("0.95")), WarningRule(warning_type="stagnant", level="warning", threshold=Decimal("365"), scope={}, enabled=True), WarningRule(warning_type="expiring", level="warning", threshold=Decimal("90"), scope={}, enabled=True), WarningRule(warning_type="overstock", level="warning", threshold=Decimal("1"), scope={}, enabled=True)])
    await session.commit()
    await enrich_demo_data(session)


async def enrich_demo_data(session: AsyncSession) -> None:
    """Add a repeatable planning dataset without duplicating existing rows.

    The generated records follow common ERP stock-entry fields: item code,
    warehouse, quantity, unit, posting date, supplier and unit price.
    """
    catalog = [
        (f"DEMO-MAT-{index:03d}", f"演示物料 {index:03d}", category, unit, Decimal(str(package)), Decimal(str(cost)), base)
        for index, (category, unit, package, cost, base) in enumerate(
            [
                ("紧固件", "件", 10, 2.4, 18), ("电缆", "米", 25, 31, 42),
                ("轴承", "件", 4, 46, 7), ("滤芯", "件", 2, 92, 5),
                ("电气元件", "件", 20, 3.2, 25), ("密封件", "件", 10, 8.5, 12),
                ("液压件", "件", 2, 185, 3), ("润滑油", "桶", 1, 240, 2),
                ("传感器", "件", 5, 128, 4), ("工具耗材", "件", 10, 15, 16),
                ("紧固件", "件", 20, 1.2, 30), ("轴承", "件", 2, 68, 6),
                ("电气元件", "件", 50, 0.8, 40), ("滤芯", "件", 4, 76, 8),
                ("密封件", "件", 5, 12, 10),
            ],
            1,
        )
    ]
    known_materials = set((await session.execute(select(Material.sku))).scalars().all())
    for sku, name, category, unit, package, cost, _ in catalog:
        if sku not in known_materials:
            session.add(Material(sku=sku, name=name, category=category, unit=unit, package_size=package, shelf_life_days=730))
    await session.flush()

    known_rules = set((await session.execute(select(SafetyStockRule.category))).scalars().all())
    for category in {item[2] for item in catalog}:
        if category not in known_rules:
            quantity = Decimal(str(next(item[6] for item in catalog if item[2] == category) * 3))
            session.add(SafetyStockRule(category=category, quantity=quantity, service_level=Decimal("0.95")))
    await session.flush()

    known_inventory = set(
        (sku, warehouse_id)
        for sku, warehouse_id in (await session.execute(select(InventorySnapshot.sku, InventorySnapshot.warehouse_id))).all()
    )
    known_usage = set(
        (sku, warehouse_id, used_at)
        for sku, warehouse_id, used_at in (await session.execute(select(UsageRecord.sku, UsageRecord.warehouse_id, UsageRecord.used_at))).all()
    )
    known_prices = set(
        (sku, supplier, recorded_at)
        for sku, supplier, recorded_at in (await session.execute(select(PriceRecord.sku, PriceRecord.supplier, PriceRecord.recorded_at))).all()
    )
    start_month = 2024 * 12 + 9
    for index, (sku, _, category, unit, package, cost, base) in enumerate(catalog, 1):
        safety = base * 3
        for warehouse_index, warehouse_id in enumerate(("W1", "W2")):
            key = (sku, warehouse_id)
            if key not in known_inventory:
                available = safety + base * 4 if (index + warehouse_index) % 2 else max(0, safety - base)
                session.add(InventorySnapshot(sku=sku, warehouse_id=warehouse_id, available_quantity=Decimal(str(available)), in_transit_quantity=Decimal(str(base if available < safety else 0)), unit_cost=cost, last_used_at=date(2026, 8, 1) - timedelta(days=index * 18)))
        for month_index in range(24):
            month_value = start_month + month_index
            used_at = date(month_value // 12, month_value % 12 + 1, 1)
            for warehouse_index, warehouse_id in enumerate(("W1", "W2")):
                key = (sku, warehouse_id, used_at)
                if key not in known_usage:
                    quantity = demo_usage_value(base, index, month_index, warehouse_index)
                    session.add(UsageRecord(sku=sku, warehouse_id=warehouse_id, quantity=Decimal(str(quantity)), used_at=used_at, work_order_id=f"DEMO-WO-{index:03d}-{warehouse_index}-{month_index:02d}"))
            supplier = f"SUP-{(index % 3) + 1:03d}"
            price_date = used_at
            price = round(float(cost) * (1 + (month_index - 12) * 0.006 + ((index % 3) - 1) * 0.015), 4)
            price_key = (sku, supplier, price_date)
            if price_key not in known_prices:
                session.add(PriceRecord(sku=sku, supplier=supplier, price=Decimal(str(price)), recorded_at=price_date))

    # Refresh only generated demo rows so each SKU has a distinct cycle/trend.
    demo_rows = list((await session.execute(select(UsageRecord).where(UsageRecord.sku.like("DEMO-MAT-%")))).scalars().all())
    base_by_index = {index: item[6] for index, item in enumerate(catalog, 1)}
    for row in demo_rows:
        try:
            index = int(row.sku.rsplit("-", 1)[-1])
        except ValueError:
            continue
        month_index = (row.used_at.year - 2024) * 12 + row.used_at.month - 10
        warehouse_index = 0 if row.warehouse_id == "W1" else 1
        row.quantity = Decimal(str(demo_usage_value(base_by_index.get(index, 10), index, month_index, warehouse_index)))

    # Extend the original showcase SKUs so the default pages also have a long history.
    for sku, warehouse_id, base, cost, supplier in (("M12-BOLT", "W1", 42, 1.8, "SUP-001"), ("BEARING-6205", "W1", 5, 36, "SUP-003"), ("CABLE-10", "W3", 80, 28, "SUP-002")):
        for month_index in range(24):
            month_value = start_month + month_index
            used_at = date(month_value // 12, month_value % 12 + 1, 1)
            if (sku, warehouse_id, used_at) not in known_usage:
                quantity = Decimal(str(round(base * (1 + ((month_index + len(sku)) % 5) * 0.05), 2)))
                session.add(UsageRecord(sku=sku, warehouse_id=warehouse_id, quantity=quantity, used_at=used_at, work_order_id=f"HIST-{sku}-{month_index:02d}"))
            if (sku, supplier, used_at) not in known_prices:
                price = Decimal(str(round(cost * (1 + (month_index - 12) * 0.004), 4)))
                session.add(PriceRecord(sku=sku, supplier=supplier, price=price, recorded_at=used_at))
    await session.commit()


def demo_usage_value(base: float, index: int, month_index: int, warehouse_index: int) -> float:
    """Generate distinct synthetic demand curves for demo-only SKUs."""
    phase = index % 4
    month = month_index + index
    if phase == 0:
        seasonal = 1 + 0.28 * sin(2 * pi * month / 12)
        trend = 1 + 0.003 * month_index
    elif phase == 1:
        seasonal = 1 + 0.22 * cos(2 * pi * month / 3)
        trend = 1 + 0.005 * month_index
    elif phase == 2:
        seasonal = 1 + 0.25 * sin(2 * pi * month / 6)
        trend = 1 - 0.003 * month_index
    else:
        seasonal = 1 + 0.12 * cos(2 * pi * month / 12)
        trend = 1 + 0.001 * month_index
    intermittent = 0 if index % 5 == 0 and month_index % 4 == 0 else 1
    return round(max(0.0, base * seasonal * trend * (1 + warehouse_index * 0.12) * intermittent), 2)
