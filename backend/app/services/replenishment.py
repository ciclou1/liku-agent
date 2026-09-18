"""安全库存优化服务：消耗速率（本地 usage_records）+ 供应交期（ERP 实测，缓存）→ 补货建议。"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.replenishment import optimize_replenishment
from app.core.config import get_settings
from app.core.erp_cache import erp_analysis_cache
from app.erp.service import ErpAnalysisService
from app.models import InventorySnapshot, Material, UsageRecord

SERVICE_LEVEL_Z = 1.65
DEFAULT_COVERAGE_MONTHS = 3.0


class ReplenishmentService:
    def __init__(self, analysis: ErpAnalysisService | None = None) -> None:
        self.analysis = analysis or ErpAnalysisService()

    # ---------- 交期 ----------

    def _lead_time_via_erp(self, sku: str) -> dict | None:
        """ERP 实测交期（下单 → 首次入库），结果进缓存（命中空 dict 表示确认无样本）。"""
        cache_key = f"erp:lead-time:{get_settings().erp_site_id}:{sku}"
        cached = erp_analysis_cache.get(cache_key)
        if cached is not None:
            return cached or None
        try:
            hit = self.analysis.lead_time(itemnum=sku)
        except Exception:  # noqa: BLE001 —— ERP 不可达时回退默认交期，不缓存失败
            return None
        erp_analysis_cache.set(cache_key, hit or {})
        return hit

    def _default_lead_months(self) -> float:
        return float(getattr(get_settings(), "replenishment_default_lead_months", 1.0) or 1.0)

    # ---------- 数据底座 ----------

    async def _monthly_pairs(self, session: AsyncSession, sku: str | None = None,
                             warehouse_id: str | None = None,
                             months: int = 12) -> list[tuple[str, float]]:
        """近 N 个有数据月份的 (月份, 消耗量) 对，时间升序。usage_records 本身按月聚合。"""
        conditions = []
        if sku:
            conditions.append(UsageRecord.sku == sku)
        if warehouse_id and warehouse_id not in ("ALL", "__all__", ""):
            conditions.append(UsageRecord.warehouse_id == warehouse_id)
        rows = (await session.execute(
            select(UsageRecord.used_at, func.sum(UsageRecord.quantity))
            .where(*conditions).group_by(UsageRecord.used_at)
            .order_by(UsageRecord.used_at.desc()).limit(months))).all()
        pairs = [(str(used_at)[:7], float(quantity or 0)) for used_at, quantity in rows]
        return list(reversed(pairs))

    async def _stock_facts(self, session: AsyncSession, sku: str,
                           warehouse_id: str | None = None) -> dict:
        conditions = [InventorySnapshot.sku == sku]
        if warehouse_id and warehouse_id not in ("ALL", "__all__", ""):
            conditions.append(InventorySnapshot.warehouse_id == warehouse_id)
        rows = (await session.execute(select(InventorySnapshot).where(*conditions))).scalars().all()
        return {
            "available": sum(float(row.available_quantity or 0) for row in rows),
            "in_transit": sum(float(row.in_transit_quantity or 0) for row in rows),
            "current_safety": sum(float(row.safety_stock or 0) for row in rows),
        }

    # ---------- 单物资 ----------

    async def optimize(self, session: AsyncSession, sku: str, warehouse_id: str | None = None,
                       coverage_months: float | None = None,
                       lead_time_months: float | None = None) -> dict:
        coverage = float(coverage_months or DEFAULT_COVERAGE_MONTHS)
        material = await session.scalar(select(Material).where(Material.sku == sku))
        pairs = await self._monthly_pairs(session, sku, warehouse_id)
        facts = await self._stock_facts(session, sku, warehouse_id)

        lead_detail: dict | None = None
        if lead_time_months is not None:
            lead, lead_source = float(lead_time_months), "manual"
        else:
            hit = await asyncio.to_thread(self._lead_time_via_erp, sku)
            if hit and hit.get("lead_months"):
                lead, lead_source, lead_detail = float(hit["lead_months"]), str(hit.get("dimension", "item")), hit
            else:
                lead, lead_source = self._default_lead_months(), "default"

        result = optimize_replenishment(
            monthly_usage=[qty for _month, qty in pairs], lead_time_months=lead,
            current_safety=facts["current_safety"], available=facts["available"],
            in_transit=facts["in_transit"],
            package_size=float(material.package_size or 1) if material else 1.0,
            z=SERVICE_LEVEL_Z, coverage_months=coverage,
        )
        payload = {
            "sku": sku,
            "name": material.name if material else sku,
            "unit": material.unit if material else "个",
            "warehouse_id": warehouse_id or "__all__",
            "monthly_usage": [{"month": month, "usage": qty} for month, qty in pairs],
            "lead_time_months": round(lead, 2), "lead_time_source": lead_source,
            "lead_time_detail": lead_detail,
            "available": facts["available"], "in_transit": facts["in_transit"],
            "current_safety": facts["current_safety"],
            "insufficient_data": result is None,
            "min_months_required": 3,
        }
        if result is not None:
            payload |= {
                "mu_monthly": result.mu_monthly, "sigma_monthly": result.sigma_monthly,
                "service_level_z": result.service_level_z,
                "suggested_safety": result.suggested_safety, "safety_gap": result.safety_gap,
                "reorder_point": result.reorder_point, "reorder_quantity": result.reorder_quantity,
                "coverage_months": result.coverage_months, "months_used": result.months_used,
                "formula_explanation": result.formula_explanation,
            }
        return payload

    # ---------- 批量 ----------

    async def batch(self, session: AsyncSession, warehouse_id: str | None = None,
                    limit: int = 100) -> dict:
        """近 12 月有消耗的 SKU 按月均消耗 Top N；交期统一取默认值（实测仅单物资详情，避免批量打 ERP）。"""
        lead = self._default_lead_months()
        latest = await session.scalar(select(func.max(UsageRecord.used_at)))
        if latest is None:
            return {"items": [], "lead_time_months": lead, "lead_time_source": "default"}
        window_start = latest.replace(year=latest.year - 1)
        conditions = [UsageRecord.used_at >= window_start]
        if warehouse_id and warehouse_id not in ("ALL", "__all__", ""):
            conditions.append(UsageRecord.warehouse_id == warehouse_id)
        usage_rows = await session.execute(
            select(UsageRecord.sku, func.sum(UsageRecord.quantity))
            .where(*conditions).group_by(UsageRecord.sku)
            .order_by(func.sum(UsageRecord.quantity).desc()).limit(min(limit, 500)))
        sku_list = [row_sku for row_sku, _qty in usage_rows.all()]
        if not sku_list:
            return {"items": [], "lead_time_months": lead, "lead_time_source": "default"}

        materials = {row.sku: row for row in (await session.execute(
            select(Material).where(Material.sku.in_(sku_list)))).scalars().all()}
        stock_rows = (await session.execute(
            select(InventorySnapshot).where(InventorySnapshot.sku.in_(sku_list)))).scalars().all()
        stock: dict[str, dict] = {}
        for row in stock_rows:
            bucket = stock.setdefault(row.sku, {"available": 0.0, "in_transit": 0.0, "current_safety": 0.0})
            bucket["available"] += float(row.available_quantity or 0)
            bucket["in_transit"] += float(row.in_transit_quantity or 0)
            bucket["current_safety"] += float(row.safety_stock or 0)
        series_rows = await session.execute(
            select(UsageRecord.sku, UsageRecord.used_at, func.sum(UsageRecord.quantity))
            .where(UsageRecord.sku.in_(sku_list), UsageRecord.used_at >= window_start)
            .group_by(UsageRecord.sku, UsageRecord.used_at))
        series: dict[str, dict[str, float]] = {}
        for row_sku, used_at, qty in series_rows.all():
            series.setdefault(row_sku, {})[str(used_at)[:7]] = float(qty or 0)

        items = []
        for sku in sku_list:
            material = materials.get(sku)
            pairs = sorted(series.get(sku, {}).items())
            result = optimize_replenishment(
                monthly_usage=[qty for _month, qty in pairs], lead_time_months=lead,
                current_safety=stock.get(sku, {}).get("current_safety", 0.0),
                available=stock.get(sku, {}).get("available", 0.0),
                in_transit=stock.get(sku, {}).get("in_transit", 0.0),
                package_size=float(material.package_size or 1) if material else 1.0,
                z=SERVICE_LEVEL_Z, coverage_months=DEFAULT_COVERAGE_MONTHS,
            )
            if result is None:
                continue
            items.append({
                "sku": sku, "name": material.name if material else sku,
                "unit": material.unit if material else "个",
                "mu_monthly": result.mu_monthly, "sigma_monthly": result.sigma_monthly,
                "current_safety": result.current_safety, "suggested_safety": result.suggested_safety,
                "safety_gap": result.safety_gap, "reorder_point": result.reorder_point,
                "reorder_quantity": result.reorder_quantity,
            })
        return {"items": items, "lead_time_months": lead, "lead_time_source": "default",
                "note": "批量模式交期取默认值，单物资详情为 ERP 实测交期"}
