"""ERP import replaces demo rows only after a complete ERP read."""
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.exceptions import BusinessError
from app.models import Base, InventorySnapshot, Material, Warehouse
from app.services.erp_import import ErpImportService


class StubImportService(ErpImportService):
    def __init__(self, source):
        self.source = source

    def _fetch(self):
        return self.source


def _source():
    return {
        "warehouses": [{"LOCATION": "P", "DESCRIPTION": "生产物资仓库"}],
        "materials": [{"ITEMNUM": "20002183", "DESCRIPTION": "石墨环垫片", "ISSUEUNIT": "个", "HDMCLASS": "密封件"}],
        "inventory": [{"ITEMNUM": "20002183", "LOCATION": "P", "AVAILABLE_QTY": 8, "UNIT_COST": 120}],
        "procurement": [{"ITEMNUM": "20002183", "ORDERQTY": 10, "UNITCOST": 120, "VENDOR": "ERP供应商", "STARTDATE": date(2024, 12, 1)}],
        "usage": [{"ITEMNUM": "20002183", "STORELOC": "P", "QUANTITY": -2, "ACTUALDATE": date(2024, 12, 2), "REFWO": "WO-1", "MATUSETRANSID": 1}],
        "receipts": [{"ITEMNUM": "20002183", "STORELOC": "P", "QUANTITY": 10, "UNITCOST": 120, "ACTUALDATE": date(2024, 12, 1), "PONUM": "PO-1", "MATRECTRANSID": 1, "ISSUETYPE": "RECEIPT"}],
    }


async def _run_import(source):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Material(sku="DEMO-MAT-001", name="演示物料"))
        await session.commit()
        service = StubImportService(source)
        try:
            result = await service.replace_with_erp_data(session)
        except BusinessError:
            rows = list((await session.execute(select(Material.sku))).scalars().all())
            outcome = (None, rows)
        else:
            rows = list((await session.execute(select(Material.sku))).scalars().all())
            inventory = list((await session.execute(select(InventorySnapshot))).scalars().all())
            warehouses = list((await session.execute(select(Warehouse))).scalars().all())
            outcome = ((result, rows, inventory, warehouses), None)
    await engine.dispose()
    return outcome


def test_import_replaces_demo_rows_after_complete_read():
    result, preserved = asyncio.run(_run_import(_source()))
    assert preserved is None
    counts, skus, inventory, warehouses = result
    assert counts["materials"] == 1
    assert skus == ["20002183"]
    assert inventory[0].available_quantity == 8
    assert warehouses[0].warehouse_id == "P"


def test_empty_erp_response_preserves_existing_rows():
    source = _source()
    source["inventory"] = []
    result, preserved = asyncio.run(_run_import(source))
    assert result is None
    assert preserved == ["DEMO-MAT-001"]
