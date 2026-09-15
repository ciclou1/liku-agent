import asyncio
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.algorithms.demand import build_features, classify_consumption, ForecastPoint
from app.algorithms.liku import PurchaseInput, calculate_purchase_recommendation
from app.algorithms.model_pool import ModelPool
from app.algorithms.liku import WarehouseStock, match_transfers
from app.algorithms.price import forecast_price
from app.algorithms.warning import detect_warnings
from app.models import InventorySnapshot, Material, PriceRecord, UsageRecord
from app.repositories.domain import DomainRepository
from app.erp.service import ErpAnalysisService


class DatabaseDomainService:
    def __init__(self) -> None:
        self.repository = DomainRepository()

    async def inventory(self, session: AsyncSession, query: str | None = None, warehouse_id: str | None = None,
                        limit: int | None = None, offset: int = 0) -> list[dict]:
        return await self.repository.inventory(session, query, warehouse_id, limit, offset)

    async def materials(self, session: AsyncSession, query: str | None = None, limit: int | None = None) -> list[dict]:
        return await self.repository.materials(session, query=query, limit=limit)

    async def health(self, session: AsyncSession) -> dict[str, float | int]:
        # Aggregate in SQL; the ERP import can contain tens of thousands of
        # inventory rows and must not be materialized for the dashboard.
        total = float(await session.scalar(select(func.coalesce(func.sum(
            InventorySnapshot.available_quantity * InventorySnapshot.unit_cost), 0))) or 0)
        stagnant_cutoff = date.fromordinal(date.today().toordinal() - 365)
        stagnant = float(await session.scalar(select(func.coalesce(func.sum(
            InventorySnapshot.available_quantity * InventorySnapshot.unit_cost), 0)).where(
            InventorySnapshot.last_used_at.is_not(None),
            InventorySnapshot.last_used_at <= stagnant_cutoff,
        )) or 0)
        sku_count = int(await session.scalar(select(func.count(func.distinct(InventorySnapshot.sku)))) or 0)
        latest_usage_date = await session.scalar(select(func.max(UsageRecord.used_at))) or date.today()
        window_start = latest_usage_date.replace(year=latest_usage_date.year - 1)
        cost_rows = await session.execute(select(InventorySnapshot.sku, func.avg(InventorySnapshot.unit_cost)).group_by(InventorySnapshot.sku))
        cost_by_sku = {sku: float(cost or 0) for sku, cost in cost_rows.all()}
        usage_rows = await session.execute(select(UsageRecord.sku, func.sum(UsageRecord.quantity)).where(UsageRecord.used_at >= window_start).group_by(UsageRecord.sku))
        consumption_value = sum(float(quantity or 0) * cost_by_sku.get(sku, 0) for sku, quantity in usage_rows.all())
        turnover_rate = round(consumption_value / total, 2) if total > 0 else 0.0
        # 价格择时预期节省：对有价格历史的 SKU 逐一预测并合计（dashboard 指标，封顶 200 个 SKU）
        saving_value = 0.0
        price_skus = (await session.execute(
            select(PriceRecord.sku).distinct().limit(200))).scalars().all()
        for sku in price_skus:
            prices = await self.repository.prices(session, sku)
            values = [row["price"] for row in prices]
            if len(values) < 3:
                continue
            try:
                timing = forecast_price(sku, values, purchase_quantity=1.0)
                saving_value += max(0.0, float(timing.expected_saving))
            except Exception:  # noqa: BLE001 —— 单个 SKU 预测失败不影响大盘指标
                continue
        return {"turnover_rate": turnover_rate, "inventory_value": total, "stagnant_value": stagnant, "saving_value": round(saving_value, 2), "sku_count": sku_count}

    async def forecast(self, session: AsyncSession, sku: str, warehouse_id: str) -> dict:
        records = await self.repository.usage(session, sku, warehouse_id)
        if not records:
            return {"sku": sku, "warehouse_id": warehouse_id, "pattern": "spare_part", "history": [], "forecast": [], "corrected": False, "model_name": "none", "backtest": {}}
        values = [item["usage"] for item in records]
        pattern = classify_consumption(values, records[0]["category"])
        output = ModelPool().predict(values, 12, pattern)
        average = sum(values) / len(values)
        deviation = (sum((value - average) ** 2 for value in values) / len(values)) ** 0.5
        points = [ForecastPoint(str(index + 1), value, max(0, value - 1.96 * deviation), value + 1.96 * deviation) for index, value in enumerate(output.values)]
        return {"sku": sku, "warehouse_id": warehouse_id, "pattern": pattern.value, "history": [item.__dict__ for item in build_features(records)], "forecast": [point.__dict__ for point in points], "corrected": False, "model_name": output.model_name, "backtest": {}}

    async def prices(self, session: AsyncSession, sku: str, purchase_quantity: float = 1.0) -> dict:
        history = await self.repository.prices(session, sku)
        values = [item["price"] for item in history]
        result = forecast_price(sku, values, purchase_quantity=purchase_quantity) if values else None
        if not result:
            return {"sku": sku, "periods": [], "prices": [], "direction": "unknown", "signal": "normal", "expected_saving": 0, "history": [], "backtest": {}}
        return result.__dict__ | {"signal": result.signal.value, "history": history, "backtest": {}}

    async def purchase_recommendation(self, session: AsyncSession, sku: str, warehouse_id: str = "W1") -> dict:
        material = await session.scalar(select(Material).where(Material.sku == sku))
        if material is None:
            # Real ERP is authoritative when the local cache has not been populated.
            if get_settings().app_env == "test":
                raise ValueError(f"unknown sku: {sku}")
            return await asyncio.to_thread(self._erp_purchase_recommendation, sku, warehouse_id)
        inventory = next((row for row in await self.repository.inventory(session, warehouse_id=warehouse_id) if row["sku"] == sku), None)
        if inventory is None:
            if get_settings().app_env == "test":
                raise ValueError(f"no inventory snapshot for {sku} at {warehouse_id}")
            return await asyncio.to_thread(self._erp_purchase_recommendation, sku, warehouse_id)
        usage = await self.repository.usage(session, sku, warehouse_id)
        if not usage:
            if get_settings().app_env == "test":
                raise ValueError(f"no usage history for {sku} at {warehouse_id}")
            return await asyncio.to_thread(self._erp_purchase_recommendation, sku, warehouse_id)
        else:
            values = [row["usage"] for row in usage]
            pattern = classify_consumption(values, material.category)
            model = ModelPool().predict(values, 3, pattern)
            model_name = model.model_name
            forecast_demand = round(sum(model.values), 4)
        prices = await self.repository.prices(session, sku)
        price_values = [row["price"] for row in prices]
        urgency = min(1.0, forecast_demand / max(inventory["available_quantity"] + inventory["safety_stock"], 1.0))
        purchase_input = PurchaseInput(sku, material.category, forecast_demand, inventory["safety_stock"], inventory["available_quantity"], inventory["in_transit"], float(material.package_size))
        preliminary = calculate_purchase_recommendation(purchase_input)
        timing = forecast_price(sku, price_values, purchase_quantity=preliminary.purchase_quantity, demand_urgency=urgency) if price_values and preliminary.purchase_quantity > 0 else None
        timing_signal = timing.signal.value if timing else ("no_purchase" if preliminary.purchase_quantity <= 0 else "normal")
        expected_saving = timing.expected_saving if timing else 0
        recommendation = calculate_purchase_recommendation(purchase_input, timing_signal, expected_saving, min(price_values) if price_values else None, max(price_values) if price_values else None)
        basis = {**recommendation.calculation_basis, "warehouse_id": warehouse_id, "current_price": price_values[-1] if price_values else None, "forecast_price_min": min(timing.prices) if timing else None, "forecast_price_max": max(timing.prices) if timing else None, "saving_formula": "(预测最高价 - 当前价) × 建议采购量" if timing and timing.signal.value == "stock_up" else "(当前价 - 预测最低价) × 建议采购量" if timing and timing.signal.value == "delay" else "无采购量，节约金额为 0"}
        result = {**recommendation.__dict__, "calculation_basis": basis, "warehouse_id": warehouse_id, "model_name": model_name, "forecast_demand": forecast_demand, "safety_stock": inventory["safety_stock"], "available_stock": inventory["available_quantity"], "in_transit": inventory["in_transit"], "package_size": float(material.package_size), "data_source": "mysql"}
        if not usage:
            result["calculation_basis"] = {**basis, "history_note": "该物料在此库房暂无领用历史，预测按 0 处理；请核对 ERP 期间数据。"}
        return result

    def _erp_purchase_recommendation(self, sku: str, warehouse_id: str) -> dict:
        """Build a recommendation from live ERP dimensions when local cache is empty."""
        analysis = ErpAnalysisService().balance_analysis(sku, request_qty=0)
        item = analysis["item"]
        stock_rows = [r for r in analysis["dimensions"]["stock_balance"]["details"]
                      if str(r.get("LOCATION")) == warehouse_id]
        reserve_rows = [r for r in analysis["dimensions"]["reservations"]["details"]
                        if str(r.get("LOCATION")) == warehouse_id]
        inventory_qty = sum(float(r.get("CURBAL") or 0) for r in stock_rows)
        reserved_qty = sum(float(r.get("RESERVEDQTY") or 0) for r in reserve_rows)
        safety_rows = [r for r in analysis["dimensions"]["safety_stock"]["details"]
                       if str(r.get("STORELOC")) == warehouse_id]
        safety = sum(float(r.get("MINLEVEL") or 0) for r in safety_rows)
        in_transit = float(analysis["summary"]["in_transit_qty"] or 0)
        available = inventory_qty + in_transit - reserved_qty
        purchase = calculate_purchase_recommendation(PurchaseInput(
            sku, str(item.get("HDMCLASS") or "未分类"), 0, safety, inventory_qty,
            in_transit, 1,
        ))
        result = {
            **purchase.__dict__, "warehouse_id": warehouse_id,
            "model_name": "erp-live", "forecast_demand": 0,
            "safety_stock": safety, "available_stock": inventory_qty,
            "in_transit": in_transit, "package_size": 1,
            "data_source": "jimu_erp",
            "inventory_quantity": inventory_qty,
            "reserved_quantity": reserved_qty,
            "available_quantity": available,
            "calculation_basis": {
                **purchase.calculation_basis,
                "warehouse_id": warehouse_id,
                "reserved_quantity": reserved_qty,
                "available_quantity": available,
                "history_note": "本地缓存无该仓库领用历史，已直接读取 ERP 实时库存/预留/在途数据。",
            },
        }
        return result

    async def warnings(self, session: AsyncSession) -> list[dict]:
        rows = await self.inventory(session)
        rules = {row.warning_type: row for row in await self.repository.warning_rules(session)}
        result = []
        for row in rows:
            normalized = dict(row)
            if normalized.get("last_used_at"):
                normalized["last_used_at"] = date.fromisoformat(normalized["last_used_at"])
            if normalized.get("expiry_date"):
                normalized["expiry_date"] = date.fromisoformat(normalized["expiry_date"])
            for warning in detect_warnings(normalized, date.today(), stagnant_days=int(rules["stagnant"].threshold) if "stagnant" in rules else 365, expiry_days=int(rules["expiring"].threshold) if "expiring" in rules else 90):
                rule = rules.get(warning.warning_type.value)
                if rule and not rule.enabled:
                    continue
                result.append({**warning.__dict__, "warning_type": warning.warning_type.value, "level": rule.level if rule else warning.level.value})
        return result

    async def transfers(self, session: AsyncSession, sku: str | None = None, target_warehouse_id: str | None = None, min_quantity: float = 0) -> list[dict]:
        rows = await self.inventory(session)
        if sku:
            rows = [row for row in rows if row["sku"] == sku]
        stocks = [WarehouseStock(row["sku"], row["warehouse_id"], "default", row["available_quantity"], row["safety_stock"], row["unit_cost"]) for row in rows]
        routes = await self.repository.routes(session)
        matches = match_transfers(stocks, routes)
        if target_warehouse_id:
            matches = [item for item in matches if item.target_warehouse_id == target_warehouse_id]
        return [item.__dict__ for item in matches if item.quantity >= min_quantity]
