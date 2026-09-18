import asyncio
import re
from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LlmGateway
from app.data.fixtures import inventory_fixture
from app.erp.service import ErpAnalysisService
from app.services.domain import DatabaseDomainService
from app.services.forecast import ForecastService
from app.services.liku import LikuService
from app.services.warning import WarningService


TOOL_DEFINITIONS = [
    {"name": "query_inventory", "description": "查询物料各仓库现货和在途数量", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "query_forecast", "description": "查询物料需求预测和历史消耗", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}, "warehouse_id": {"type": "string"}}}},
    {"name": "generate_purchase", "description": "根据数据库库存和预测生成采购建议", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}, "warehouse_id": {"type": "string"}}}},
    {"name": "query_warnings", "description": "查询库存风险预警", "input_schema": {"type": "object", "properties": {}}},
    {"name": "query_arrival_rate", "description": "查询采购到货率（物资/供应商/时间段维度）", "input_schema": {"type": "object", "properties": {"itemnum": {"type": "string"}, "supplier": {"type": "string"}}}},
    {"name": "query_inventory_stats", "description": "查询库存统计报表（总金额/SKU数/呆滞金额/周转率/仓库分布）", "input_schema": {"type": "object", "properties": {}}},
    {"name": "query_consumption", "description": "查询物资消耗情况（逐月领用量/累计/消耗排名）", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}}},
]


class ControlledSql:
    allowed_tables = {"materials", "inventory_snapshots", "usage_records", "price_records"}

    def validate(self, query: str) -> str:
        normalized = query.strip().lower()
        if ";" in normalized or "--" in normalized or "/*" in normalized or "union" in normalized or not normalized.startswith("select"):
            raise ValueError("只允许单条只读 SELECT 查询")
        tables = set(re.findall(r"\bfrom\s+([a-z_]+)|\bjoin\s+([a-z_]+)", normalized))
        flattened = {item for pair in tables for item in pair if item}
        if not flattened.issubset(self.allowed_tables):
            raise ValueError("查询表不在只读白名单中")
        return query

    def execute(self, query: str, rows: list[dict]) -> list[dict]:
        self.validate(query)
        return rows[:100]

    async def execute_session(self, session: AsyncSession, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.validate(query)
        result = await session.execute(text(query), parameters or {})
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in result.fetchmany(100)]

    def tables(self, query: str) -> set[str]:
        self.validate(query)
        return set(re.findall(r"\b(?:from|join)\s+([a-z_]+)", query.lower()))


def redact_sensitive(value: Any) -> Any:
    sensitive = {"token", "password", "secret", "api_key", "authorization"}
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in sensitive else redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _signal_text(value: str) -> str:
    return {"stock_up": "建议提前备货", "delay": "建议延后采购", "normal": "建议按计划采购"}.get(value, value)


def _pattern_text(value: str) -> str:
    return {"stable": "稳定消耗", "intermittent": "间歇消耗", "spare_part": "备件型"}.get(value, value)


def format_tool_facts(tool_name: str, result: Any) -> str:
    if tool_name == "query_inventory" and isinstance(result, list):
        if not result:
            return "没有找到符合条件的库存记录，请确认物料名称、物料编码或仓库范围。"
        facts = [f"{item['name']}（{item['warehouse_name']}，{item['warehouse_id']}）可用 {item['available_quantity']} {item.get('unit', '件')}，在途 {item['in_transit']}" for item in result]
        return "已查到现货：" + "；".join(facts) + "。"
    if tool_name == "query_forecast" and isinstance(result, dict):
        values = result.get("forecast", [])[:3]
        forecast = "、".join(str(round(float(item["value"]), 2)) for item in values) or "暂无预测"
        return f"{result['sku']} 在 {result['warehouse_id']} 的消耗模式为{_pattern_text(result['pattern'])}，未来三期预测约为 {forecast}。"
    if tool_name == "generate_purchase" and isinstance(result, dict):
        return f"{result['sku']} 在 {result.get('warehouse_id', '目标仓库')} 建议采购 {result['purchase_quantity']}，预测需求 {result.get('forecast_demand', result.get('net_gap'))}，{_signal_text(result['timing_signal'])}，预计节省 {result['expected_saving']}。"
    if tool_name == "query_warnings" and isinstance(result, list):
        if not result:
            return "当前没有开放库存预警。"
        first = result[0]
        if "warehouse_id" not in first or "warning_type" not in first:
            return f"共 {len(result)} 条预警，首条为 {first.get('sku', '未知物料')} 的{first.get('message', '风险')}"
        return f"当前共有 {len(result)} 条库存预警，首条为 {first['sku']}（{first['warehouse_id']}）的{first['warning_type']}风险：{first['message']}。"
    if tool_name == "query_arrival_rate" and isinstance(result, dict):
        if result.get("error"):
            return str(result["error"])
        rate = result.get("overall_rate")
        if rate is None:
            return "查询范围内没有符合条件的采购合同数据，无法计算到货率。"
        scope = result.get("itemnum") or result.get("supplier")
        window = f"{result.get('start')} ~ {result.get('end')}" if result.get("start") else "全部时间"
        text = f"{scope + ' ' if scope else ''}在 {window} 的到货率 {rate * 100:.1f}%（有效合同 {result.get('contract_lines', 0)} 行，合同量 {result.get('total_ordered', 0)}，已入库 {result.get('total_received', 0)}）。"
        if result.get("window_applied"):
            text += "（未指定时间段时默认统计近 12 个月；可通过日期参数查询其他区间）"
        months = [f"{row['MONTH']} {(row.get('rate') or 0) * 100:.1f}%" for row in (result.get("by_month") or [])[:6] if row.get("MONTH")]
        if months:
            text += " 近几月：" + "、".join(months) + "。"
        suppliers = [f"{row['VENDOR']} {(row.get('rate') or 0) * 100:.1f}%" for row in (result.get("by_supplier") or [])[:3]]
        if suppliers:
            text += " 主要供应商到货率：" + "、".join(suppliers) + "。"
        return text + " 口径：" + str(result.get("formula_explanation", "已入库数量 / 合同数量")) + "。"
    if tool_name == "query_inventory_stats" and isinstance(result, dict):
        if not result:
            return "当前没有库存统计数据（请先在数据库配置页导入 ERP 数据）。"
        text = (f"库存总金额 {result.get('inventory_value', 0):.0f} 元，SKU {result.get('sku_count', 0)} 个，"
                f"呆滞金额 {result.get('stagnant_value', 0):.0f} 元，周转率 {result.get('turnover_rate', 0)}，"
                f"累计降本 {result.get('saving_value', 0):.0f} 元。")
        warehouses = result.get("warehouses") or []
        if warehouses:
            text += " 库存金额前列仓库：" + "、".join(
                f"{row.get('warehouse_name', row.get('warehouse_id', ''))} {row.get('amount', 0):.0f} 元" for row in warehouses[:3]) + "。"
        return text
    if tool_name == "query_consumption" and isinstance(result, dict):
        monthly = result.get("monthly") or []
        if result.get("sku"):
            if not monthly:
                return f"{result['sku']} 近 12 个月没有领用记录。"
            text = f"{result['sku']} 近 12 个月累计领用 {result.get('total_qty', 0)}，近 3 个月 {result.get('last_3m_qty', 0)}"
            if result.get("last_used_at"):
                text += f"，最近领用 {result['last_used_at'][:10]}"
            detail = "、".join(f"{row['month']} {row['qty']:.0f}" for row in monthly[-6:])
            return text + "。逐月：" + detail + "。"
        top = result.get("top_items") or []
        if not top:
            return "近 12 个月没有领用记录。"
        return "近 12 个月消耗最多的物资：" + "、".join(
            f"{item.get('name', item['sku'])} {item.get('qty', 0):.0f}" for item in top[:5]) + "。"
    return "已完成查询。"


class ChatbotService:
    def __init__(self, gateway: LlmGateway | None = None) -> None:
        self.gateway = gateway or LlmGateway()
        self.sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.forecast = ForecastService()
        self.liku = LikuService()
        self.warnings = WarningService()
        self.audit_events: list[dict[str, str]] = []

    async def _resolve_sku(self, message: str, session: AsyncSession | None) -> str | None:
        match = re.search(r"[A-Za-z0-9][A-Za-z0-9\-]{3,}", message)
        code = match.group() if match else None
        if session:
            query = code or message.strip()[:40] or None
            materials = await DatabaseDomainService().materials(session, query=query, limit=50)
            lowered = message.lower()
            if code:
                exact = next((item for item in materials if item["sku"].lower() == code.lower()), None)
                if exact:
                    return exact["sku"]
            for item in materials:
                if item["sku"].lower() in lowered or item["name"] in message:
                    return item["sku"]
            if code:
                return code
        aliases = {"m12螺栓": "M12-BOLT", "螺栓": "M12-BOLT", "电缆": "CABLE-10", "轴承": "BEARING-6205", "滤芯": "FILTER-A", "保险丝": "FUSE-10A"}
        return next((sku for alias, sku in aliases.items() if alias in message.lower()), None) or code

    async def _tool_result(self, message: str, session: AsyncSession | None = None) -> tuple[str | None, object, list[str]]:
        sku = await self._resolve_sku(message, session)
        # 新意图放在既有关键词之前："总库存/统计" 含 "库存"、"消耗" 在旧预测意图里，
        # 顺序颠倒会被旧意图抢先命中。
        if any(keyword in message for keyword in ("统计", "报表", "大盘", "库存金额", "总库存", "周转")):
            if session:
                domain = DatabaseDomainService()
                health = await domain.health(session, include_saving=False)
                wh_stats = await domain.warehouse_stats(session)
                payload = {**health, "total_skus": wh_stats["total_skus"],
                           "warehouses": wh_stats["warehouses"][:8]}
                return "query_inventory_stats", payload, ["库存快照", "领用流水", "价格历史"]
            return "query_inventory_stats", {}, ["演示数据"]
        if "到货" in message:
            if session:
                itemnum = sku
                supplier = None
                if "供应商" in message:
                    supplier = message.split("供应商", 1)[1].split("的", 1)[0].strip()[:60] or None
                try:
                    result = await asyncio.to_thread(
                        ErpAnalysisService().arrival_rate, itemnum, supplier)
                except Exception:  # noqa: BLE001 —— ERP 不可达时问答降级，不抛 5xx
                    result = {"overall_rate": None, "by_month": [], "by_supplier": [],
                              "error": "ERP 暂时不可达，请稍后再试"}
                return "query_arrival_rate", result, ["采购合同", "入库流水（积木 ERP 实时）"]
            return "query_arrival_rate", {}, ["演示数据"]
        if any(keyword in message for keyword in ("消耗", "领用情况", "领用量")):
            if session:
                summary = await DatabaseDomainService().consumption_summary(session, sku)
                return "query_consumption", summary, ["领用流水"]
            return "query_consumption", {}, ["演示数据"]
        if any(keyword in message for keyword in ("库存", "现货", "哪个仓库", "哪家仓库", "哪里有货")):
            if session:
                return "query_inventory", await DatabaseDomainService().inventory(session, sku), ["库存快照", "物料主数据"]
            rows = [row for row in inventory_fixture() if not sku or row["sku"] == sku]
            return "query_inventory", rows, ["库存快照", "演示数据"]
        if any(keyword in message for keyword in ("预测", "需求", "消耗趋势", "够不够用")):
            selected_sku = sku or "M12-BOLT"
            if session:
                return "query_forecast", await DatabaseDomainService().forecast(session, selected_sku, "W1"), ["领用流水", "需求预测模型"]
            return "query_forecast", self.forecast.get(selected_sku, "W1"), ["领用流水", "需求预测模型"]
        if "采购" in message:
            selected_sku = sku or "M12-BOLT"
            if session:
                return "generate_purchase", await DatabaseDomainService().purchase_recommendation(session, selected_sku, "W1"), ["库存快照", "领用流水", "采购价历史"]
            return "generate_purchase", self.liku.recommend({"sku": selected_sku, "category": "紧固件", "forecast_demand": 130, "safety_stock": 80, "available_stock": 120, "in_transit": 20, "package_size": 10}), ["预测模型", "库存快照", "利库引擎"]
        if any(keyword in message for keyword in ("呆滞", "预警", "风险", "临期", "超储")):
            if session:
                return "query_warnings", await DatabaseDomainService().warnings(session), ["库存快照", "预警规则"]
            return "query_warnings", self.warnings.list(), ["库存快照", "预警规则"]
        return None, None, []

    async def chat(self, message: str, session_id: str | None = None, session: AsyncSession | None = None) -> dict:
        session_id = session_id or str(uuid4())
        tool_name, tool_result, sources = await self._tool_result(message, session)
        self.audit_events.append({"action": "chat_tool", "tool": tool_name or "none", "session_id": session_id})
        self.sessions[session_id].append({"role": "user", "content": message})
        if tool_name:
            # 数值由确定性工具给出，不再同步调 LLM 复述（网关 30s×3 会拖死问答）。
            facts = format_tool_facts(tool_name, tool_result)
            answer = f"{facts}\n数据来源：{'、'.join(sources)}。"
        else:
            completion = await self.gateway.complete(self.sessions[session_id], TOOL_DEFINITIONS)
            answer = completion["content"] or "请告诉我物料名称或编码，以及你要查询库存、预测、采购或预警。"
        self.sessions[session_id].append({"role": "assistant", "content": answer})
        return {"session_id": session_id, "answer": answer, "sources": sources, "tool_name": tool_name}

    def session(self, session_id: str) -> list[dict[str, str]]:
        return list(self.sessions.get(session_id, []))

    def load_session(self, session_id: str, messages: list[dict[str, object]]) -> None:
        self.sessions[session_id] = [{"role": str(item["role"]), "content": str(item["content"])} for item in messages]
