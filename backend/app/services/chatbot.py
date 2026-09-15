import re
from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LlmGateway
from app.data.fixtures import inventory_fixture
from app.services.domain import DatabaseDomainService
from app.services.forecast import ForecastService
from app.services.liku import LikuService
from app.services.warning import WarningService


TOOL_DEFINITIONS = [
    {"name": "query_inventory", "description": "查询物料各仓库现货和在途数量", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "query_forecast", "description": "查询物料需求预测和历史消耗", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}, "warehouse_id": {"type": "string"}}}},
    {"name": "generate_purchase", "description": "根据数据库库存和预测生成采购建议", "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}, "warehouse_id": {"type": "string"}}}},
    {"name": "query_warnings", "description": "查询库存风险预警", "input_schema": {"type": "object", "properties": {}}},
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
        if session:
            materials = await DatabaseDomainService().materials(session)
            for item in materials:
                if item["sku"].lower() in message.lower() or item["name"] in message:
                    return item["sku"]
        aliases = {"m12螺栓": "M12-BOLT", "螺栓": "M12-BOLT", "电缆": "CABLE-10", "轴承": "BEARING-6205", "滤芯": "FILTER-A", "保险丝": "FUSE-10A"}
        return next((sku for alias, sku in aliases.items() if alias in message.lower()), None)

    async def _tool_result(self, message: str, session: AsyncSession | None = None) -> tuple[str | None, object, list[str]]:
        sku = await self._resolve_sku(message, session)
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
            # The LLM may explain facts, but deterministic business facts are always the answer source.
            await self.gateway.complete([{"role": "user", "content": f"请解释以下业务结果：{redact_sensitive(tool_result)}"}], TOOL_DEFINITIONS)
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
