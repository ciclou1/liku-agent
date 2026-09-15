from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventorySnapshot, Material, PriceRecord, ProcurementOrder, UsageRecord
from app.models.operations import ChatMessage, ChatSession, ForecastRecord, PriceTarget, PurchaseRecommendationRecord, SafetyStockRule, WarningRule


class PersistenceService:
    async def load_rows(self, session: AsyncSession, entity: str, rows: list[dict]) -> int:
        loaders = {
            "materials": self._load_materials,
            "inventory_snapshots": self._load_inventory,
            "usage_records": self._load_usage,
            "price_records": self._load_prices,
            "procurement_orders": self._load_procurement,
        }
        loader = loaders.get(entity)
        if loader is None:
            raise ValueError(f"不支持的数据实体: {entity}")
        count = 0
        for row in rows:
            await loader(session, row)
            count += 1
        await session.commit()
        return count

    async def save_chat(self, session: AsyncSession, session_id: str, user_id: str | None, user_message: str, answer: str, sources: list[str]) -> None:
        chat_session = await session.get(ChatSession, session_id)
        if chat_session is None:
            chat_session = ChatSession(id=session_id, user_id=user_id, title=user_message[:160])
            session.add(chat_session)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add_all([ChatMessage(session_id=session_id, role="user", content=user_message, sources=[], created_at=now), ChatMessage(session_id=session_id, role="assistant", content=answer, sources=sources, created_at=now)])
        await session.commit()

    async def chat_messages(self, session: AsyncSession, session_id: str) -> list[dict[str, object]]:
        rows = (await session.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.id))).scalars().all()
        return [{"role": row.role, "content": row.content, "sources": row.sources} for row in rows]

    async def _load_materials(self, session: AsyncSession, row: dict) -> None:
        item = await session.scalar(select(Material).where(Material.sku == str(row["sku"])))
        values = {"sku": str(row["sku"]), "name": str(row["name"]), "category": str(row.get("category") or "未分类"), "unit": str(row.get("unit") or "件"), "package_size": Decimal(str(row.get("package_size") or 1)), "shelf_life_days": int(row["shelf_life_days"]) if row.get("shelf_life_days") else None}
        if item is None:
            session.add(Material(**values))
        else:
            for key, value in values.items():
                setattr(item, key, value)

    async def _load_inventory(self, session: AsyncSession, row: dict) -> None:
        item = await session.scalar(select(InventorySnapshot).where(InventorySnapshot.sku == str(row["sku"]), InventorySnapshot.warehouse_id == str(row["warehouse_id"])))
        values = {"sku": str(row["sku"]), "warehouse_id": str(row["warehouse_id"]), "available_quantity": Decimal(str(row.get("available_quantity") or 0)), "in_transit_quantity": Decimal(str(row.get("in_transit_quantity") or 0)), "unit_cost": Decimal(str(row.get("unit_cost") or 0)), "last_used_at": self._parse_date(row.get("last_used_at")), "expiry_date": self._parse_date(row.get("expiry_date"))}
        if item is None:
            session.add(InventorySnapshot(**values))
        else:
            for key, value in values.items():
                setattr(item, key, value)

    async def _load_usage(self, session: AsyncSession, row: dict) -> None:
        session.add(UsageRecord(sku=str(row["sku"]), warehouse_id=str(row["warehouse_id"]), quantity=Decimal(str(row.get("quantity") or 0)), used_at=self._parse_date(row["used_at"]) or date.today(), work_order_id=str(row.get("work_order_id")) if row.get("work_order_id") else None))

    async def _load_prices(self, session: AsyncSession, row: dict) -> None:
        session.add(PriceRecord(sku=str(row["sku"]), supplier=str(row["supplier"]), price=Decimal(str(row.get("price") or 0)), recorded_at=self._parse_date(row["recorded_at"]) or date.today()))

    async def _load_procurement(self, session: AsyncSession, row: dict) -> None:
        session.add(ProcurementOrder(sku=str(row["sku"]), warehouse_id=str(row["warehouse_id"]), supplier=str(row["supplier"]), quantity=Decimal(str(row.get("quantity") or 0)), unit_price=Decimal(str(row.get("unit_price") or 0)), ordered_at=self._parse_date(row["ordered_at"]) or date.today()))

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if value:
            return date.fromisoformat(str(value)[:10])
        return None
    async def list_recommendations(self, session: AsyncSession) -> list[dict]:
        rows = (await session.execute(select(PurchaseRecommendationRecord).order_by(PurchaseRecommendationRecord.created_at.desc(), PurchaseRecommendationRecord.id.desc()))).scalars().all()
        latest: dict[tuple[str, str], PurchaseRecommendationRecord] = {}
        for row in rows:
            basis = row.calculation_basis or {}
            warehouse_id = row.warehouse_id or str(basis.get("warehouse_id") or "W1")
            latest.setdefault((row.sku, warehouse_id), row)
        result = []
        for row in latest.values():
            basis = row.calculation_basis or {}
            warehouse_id = row.warehouse_id or str(basis.get("warehouse_id") or "W1")
            quantity = float(row.quantity)
            status = "no_purchase" if quantity <= 0 else row.status
            timing = "no_purchase" if quantity <= 0 else row.timing_signal
            result.append({"id": row.id, "sku": row.sku, "category": row.category, "warehouse_id": warehouse_id, "purchase_quantity": quantity, "status": status, "timing_signal": timing, "expected_saving": 0.0 if quantity <= 0 else float(row.expected_saving), "calculation_basis": basis, "summary": basis.get("summary") or f"{row.sku} 在 {warehouse_id} 的建议采购量为 {quantity}。"})
        return result

    async def update_recommendation(self, session: AsyncSession, item_id: str, status: str | None = None, quantity: float | None = None) -> dict | None:
        row = await session.get(PurchaseRecommendationRecord, item_id)
        if row is None:
            return None
        if quantity is not None:
            row.quantity = Decimal(str(quantity))
            row.calculation_basis = {**(row.calculation_basis or {}), "reviewed_quantity": quantity}
        if status is not None:
            row.transition(status)
        await session.commit()
        return (await self.list_recommendations(session))[-1] if False else {"id": row.id, "sku": row.sku, "category": row.category, "purchase_quantity": float(row.quantity), "status": row.status, "timing_signal": row.timing_signal, "expected_saving": float(row.expected_saving), "calculation_basis": row.calculation_basis}

    async def save_forecast(self, session: AsyncSession, result: dict) -> int:
        await session.execute(delete(ForecastRecord).where(ForecastRecord.sku == result["sku"], ForecastRecord.warehouse_id == result["warehouse_id"]))
        records = [ForecastRecord(sku=result["sku"], warehouse_id=result["warehouse_id"], period=point["period"], value=Decimal(str(point["value"])), lower_bound=Decimal(str(point["lower"])), upper_bound=Decimal(str(point["upper"])), pattern=result["pattern"], corrected=result.get("corrected", False)) for point in result["forecast"]]
        session.add_all(records)
        await session.commit()
        return len(records)

    async def save_recommendation(self, session: AsyncSession, result: dict) -> PurchaseRecommendationRecord:
        quantity = Decimal(str(result["purchase_quantity"]))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        record = PurchaseRecommendationRecord(sku=result["sku"], warehouse_id=result.get("warehouse_id"), category=result["category"], quantity=quantity, status="no_purchase" if quantity <= 0 else result.get("status", "generated"), timing_signal="no_purchase" if quantity <= 0 else result.get("timing_signal", "normal"), expected_saving=Decimal("0") if quantity <= 0 else Decimal(str(result.get("expected_saving", 0))), calculation_basis=result.get("calculation_basis", {}), created_at=now, updated_at=now)
        session.add(record)
        await session.commit()
        return record

    async def save_safety_stock(self, session: AsyncSession, config: dict) -> SafetyStockRule:
        record = await session.scalar(select(SafetyStockRule).where(SafetyStockRule.category == config["category"]))
        if record is None:
            record = SafetyStockRule(category=config["category"], quantity=Decimal(str(config["quantity"])), service_level=Decimal(str(config.get("service_level", 0.95))))
            session.add(record)
        else:
            record.quantity = Decimal(str(config["quantity"]))
            record.service_level = Decimal(str(config.get("service_level", 0.95)))
        await session.commit()
        return record

    async def save_warning_rule(self, session: AsyncSession, config: dict) -> WarningRule:
        record = await session.scalar(select(WarningRule).where(WarningRule.warning_type == config["warning_type"]))
        if record is None:
            record = WarningRule(warning_type=config["warning_type"], threshold=Decimal(str(config["threshold"])), level=config["level"], scope=config.get("scope", {}), enabled=config.get("enabled", True))
            session.add(record)
        else:
            record.threshold = Decimal(str(config["threshold"]))
            record.level = config["level"]
            record.scope = config.get("scope", {})
            record.enabled = config.get("enabled", True)
        await session.commit()
        return record

    async def save_price_target(self, session: AsyncSession, sku: str, enabled: bool) -> PriceTarget:
        record = await session.scalar(select(PriceTarget).where(PriceTarget.sku == sku))
        if record is None:
            record = PriceTarget(sku=sku, enabled=enabled)
            session.add(record)
        else:
            record.enabled = enabled
        await session.commit()
        return record

    async def price_targets(self, session: AsyncSession) -> list[str]:
        rows = (await session.execute(select(PriceTarget).where(PriceTarget.enabled.is_(True)).order_by(PriceTarget.sku))).scalars().all()
        return [row.sku for row in rows]
