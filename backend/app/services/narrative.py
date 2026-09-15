import json
from typing import Any

from app.core.config import get_settings
from app.core.llm import LlmGateway


class NarrativeService:
    def __init__(self, gateway: LlmGateway | None = None) -> None:
        self.gateway = gateway or LlmGateway()

    async def explain(self, kind: str, data: dict[str, Any]) -> str:
        text, _source = await self.explain_with_source(kind, data)
        return text

    async def explain_with_source(self, kind: str, data: dict[str, Any]) -> tuple[str, str]:
        """返回 (文本, 来源)，来源：llm=大模型生成 / template=确定性模板降级。"""
        fallback = self._fallback(kind, data)
        if get_settings().app_env == "test":
            return fallback, "template"
        prompt = [
            {"role": "system", "content": "你是企业库存计划助手。只根据给定结构化数据用简洁中文解释，不修改任何数字，不输出 JSON，不编造数据。"},
            {"role": "user", "content": f"请解释以下{kind}结果，给出结论、关键依据和下一步建议：\n{json.dumps(data, ensure_ascii=False, default=str)}"},
        ]
        try:
            result = await self.gateway.complete(prompt)
        except Exception:  # noqa: BLE001 —— 模型不可用一律降级模板
            return fallback, "template"
        content = str(result.get("content", "")).strip()
        if content and "确定性业务工具" not in content and "查看返回" not in content:
            return content, "llm"
        return fallback, "template"

    @staticmethod
    def _fallback(kind: str, data: dict[str, Any]) -> str:
        if kind == "平衡利库分析":
            item = data.get("item") or {}
            pr = data.get("pr_line") or {}
            s = data.get("summary") or {}
            c = data.get("conclusion") or {}
            demand = data.get("request_qty", 0)
            head = f"{item.get('ITEMNUM', '')} {item.get('DESCRIPTION', '')}".strip() or "该物资"
            if pr:
                head += f"（立项申请 {pr.get('PRNUM', '')} 行 {pr.get('PRLINENUM', '-')}，申请量 {demand}）"
            if c.get("status") == "satisfied":
                action = "建议走平衡利库：优先领用/调拨现有库存与在途资源，本次无需新增采购。"
            elif c.get("status") == "partial":
                action = f"现有可用量仅能覆盖部分需求，建议按缺口采购 {c.get('suggested_purchase_qty', 0)}，其余由库存平衡解决。"
            elif c.get("status") == "purchase":
                action = f"可用量为零或为负，建议足额采购 {c.get('suggested_purchase_qty', 0)}。"
            else:
                action = "未关联申请数量，仅展示库存状况；如可用量低于安全库存，建议按缺口补库。"
            return (f"{head}。可用量 {s.get('available_qty', 0)}"
                    f" = 库存 {s.get('stock_qty', 0)} + 在途 {s.get('in_transit_qty', 0)} − 预留 {s.get('reserved_qty', 0)}；"
                    f"历史累计采购 {s.get('history_purchase_qty', 0)}，工单累计领用 {s.get('work_order_issued_qty', 0)}，"
                    f"安全库存 {s.get('safety_stock_qty', 0)}。{action}"
                    f"（叠加安全库存的参考采购量 {c.get('suggested_purchase_with_safety', 0)}。）")
        if kind == "采购建议":
            if float(data.get("purchase_quantity", 0)) <= 0:
                return f"{data.get('sku')} 在 {data.get('warehouse_id', '目标仓库')} 当前无需采购；可用库存已覆盖预测需求和安全库存。"
            signal = {"stock_up": "建议提前备货", "delay": "建议延后采购", "normal": "建议按计划采购", "no_purchase": "当前无需采购"}.get(str(data.get("timing_signal")), "建议按计划采购")
            return f"{data.get('sku')} 在 {data.get('warehouse_id', '目标仓库')} 建议采购 {data.get('purchase_quantity')}；预测需求 {data.get('forecast_demand', data.get('net_gap'))}，{signal}，预计节省 {data.get('expected_saving', 0)}。"
        if kind == "需求预测":
            values = [round(float(item.get("value", 0)), 2) for item in data.get("forecast", [])[:3]]
            return f"{data.get('sku')} 近期属于{data.get('pattern')}，未来三期预测约为 {values}，请结合安全库存和维修计划确认采购节奏。"
        if kind == "价格择时":
            signal = {"stock_up": "建议提前锁价", "delay": "建议延后采购", "normal": "建议按计划采购"}.get(str(data.get("signal")), "建议按计划采购")
            return f"{data.get('sku')} 当前价格趋势为 {data.get('direction')}，{signal}，预计节省 {data.get('expected_saving', 0)}。"
        return "已根据业务数据生成分析结果。"
