import json
import re
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
        system_instruction = "你是企业库存计划助手。只根据给定结构化数据用简洁中文解释，不修改任何数字，不输出 JSON，不编造数据。"
        if kind == "平衡利库工作台综合解读":
            system_instruction += "必须保留并先总结库存面板的库存量、在途量、预留量、安全库存和可用量结论，再分别归纳采购建议、利库调剂、需求预测、价格择时和预警；没有数据时明确写暂无数据。"
        prompt = [
            {"role": "system", "content": system_instruction},
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

    async def analyze_sections(self, data: dict[str, Any]) -> tuple[dict[str, str], str]:
        """一次模型调用生成各分页的判断、影响和动作建议。"""
        fallback = self._section_analysis_fallback(data)
        if get_settings().app_env == "test":
            return fallback, "template"
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是库存计划分析师。请只根据输入数据进行业务分析，不修改任何数字，不编造数据。"
                    "必须判断原因、影响和下一步动作，而不是简单复述。只返回合法 JSON，不要 Markdown，"
                    "JSON 键固定为 inventory、purchase、transfers、forecast、price、warnings、summary，"
                    "每个值是一段简洁中文分析文字。没有数据时写明暂无数据及原因。"
                ),
            },
            {"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)},
        ]
        raw = ""
        try:
            result = await self.gateway.complete(prompt)
            raw = str(result.get("content", "")).strip()
            if raw.startswith("```"):
                raw = raw.strip("`").replace("json\n", "", 1).strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
                # 兼容网关在 JSON 前后附加说明文字的情况。
                start, end = raw.find("{"), raw.rfind("}")
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(raw[start:end + 1])
                    except json.JSONDecodeError:
                        parsed = None
            if isinstance(parsed, str) and parsed.lstrip().startswith("{"):
                try:
                    parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    pass
            if isinstance(parsed, dict) and all(key in parsed for key in fallback):
                return {key: str(parsed[key]) for key in fallback}, "llm-analysis"
            # 网关有时会返回 Markdown 而不是严格 JSON；按标题切分，仍保留模型分析结果。
            if raw and len(raw) > 30:
                labels = [("inventory", "库存"), ("purchase", "采购"), ("transfers", "调剂"), ("forecast", "预测"), ("price", "价格"), ("warnings", "预警"), ("summary", "总结")]
                found: dict[str, str] = {}
                matches = []
                for key, label in labels:
                    match = re.search(rf"(?:^|\n)\s*(?:#+\s*)?(?:{label}|.*{label}.*分析|.*{label}.*结论)[:：]?", raw, flags=re.IGNORECASE)
                    if match:
                        matches.append((match.start(), key, match.end()))
                matches.sort()
                for index, (start, key, end) in enumerate(matches):
                    stop = matches[index + 1][0] if index + 1 < len(matches) else len(raw)
                    found[key] = raw[end:stop].strip(" \n:-：")
                if found:
                    for key in fallback:
                        found.setdefault(key, fallback[key])
                    return found, "llm-analysis"
                fallback["summary"] = raw
                return fallback, "llm-analysis"
        except Exception:  # noqa: BLE001 - 分析失败降级为确定性判断
            if raw and len(raw) > 30:
                fallback["summary"] = raw
                return fallback, "llm-analysis"
        return fallback, "template-analysis"

    @staticmethod
    def _section_analysis_fallback(data: dict[str, Any]) -> dict[str, str]:
        inventory = data.get("inventory_balance") or {}
        summary = inventory.get("summary") or {}
        conclusion = inventory.get("conclusion") or {}
        purchase = data.get("purchase_recommendation") or {}
        transfer_rows = data.get("transfer_recommendations") or []
        forecast = data.get("demand_forecast") or {}
        price = data.get("price_timing") or {}
        warnings = data.get("warnings") or []
        available = float(summary.get("available_qty") or 0)
        demand = float(inventory.get("request_qty") or 0)
        inventory_analysis = (
            f"当前可用量为 {available}，库存 {summary.get('stock_qty', 0)}、在途 {summary.get('in_transit_qty', 0)}、"
            f"预留 {summary.get('reserved_qty', 0)}、安全库存 {summary.get('safety_stock_qty', 0)}。"
            f"影响判断：{conclusion.get('text', '暂无申请需求，暂按库存状态观察')}"
        )
        purchase_qty = float(purchase.get("purchase_quantity") or 0)
        purchase_analysis = (
            f"采购建议量为 {purchase_qty}，预测需求 {purchase.get('forecast_demand', 0)}。"
            f"原因判断：当前采购时机为 {purchase.get('timing_signal', '暂无')}；"
            f"下一步：{'无需新增采购，关注在途到货和后续消耗' if purchase_qty <= 0 else '结合调剂候选和交期确认采购数量后再下单'}。"
        )
        transfer_analysis = (
            f"发现 {len(transfer_rows)} 条调剂候选。"
            f"影响判断：{'存在跨仓平衡空间，优先核对调出仓可用量和运输时效' if transfer_rows else '当前没有同时满足富余仓和缺口仓条件的调剂路径'}。"
        )
        forecast_analysis = (
            f"消耗模式为 {forecast.get('pattern', '暂无历史')}，未来预测为 {forecast.get('next_values', [])}。"
            "分析建议：将预测趋势与安全库存、维修计划结合，判断是否需要提前采购或调拨。"
        )
        price_analysis = (
            f"价格趋势为 {price.get('direction', '暂无')}，采购信号为 {price.get('signal', '暂无')}，"
            f"预计节省 {price.get('expected_saving', 0)}。"
            "影响判断：价格信号只影响采购时点，不改变库存可用量；缺少历史报价时不应据此锁价。"
        )
        warning_analysis = (
            f"当前发现 {len(warnings)} 条预警。"
            f"下一步：{'优先处理严重预警并核查对应仓库和物料' if warnings else '暂无需处理的风险，继续关注库存与安全库存变化'}。"
        )
        safety = float(summary.get("safety_stock_qty") or 0)
        in_transit = float(summary.get("in_transit_qty") or 0)
        reserve = float(summary.get("reserved_qty") or 0)
        price_signal = str(price.get("signal") or "normal")
        if purchase_qty <= 0 and available >= demand + safety:
            balance_strategy = (
                "当前不建议新增采购；先按需求分配现有可用量，优先消化可用现货，跟踪在途到货，"
                "并在到货后重新核对库存结构。"
            )
        elif transfer_rows:
            balance_strategy = (
                f"优先执行跨仓调剂（已有 {len(transfer_rows)} 条候选），调剂仍不足时再按缺口采购 {purchase_qty}；"
                "调拨完成后重新计算可用量，避免调拨和采购重复覆盖同一缺口。"
            )
        else:
            balance_strategy = (
                f"当前没有可执行调剂路径，按可用量缺口评估采购 {purchase_qty}；"
                "下单前核对申请量、在途合同和预留工单，防止重复采购。"
            )
        if in_transit > max(available - in_transit, 0) and purchase_qty <= 0:
            balance_strategy += " 在途量占比较高，重点跟踪合同到货，不建议提前追加订单。"
        if price_signal == "delay":
            balance_strategy += " 价格信号偏向延后采购，非紧急需求可等待价格窗口。"
        elif price_signal == "stock_up":
            balance_strategy += " 价格信号偏向提前锁价，但应在调剂和在途核对完成后执行。"
        warning_step = "先处理预警并确认库存口径。" if warnings else "当前无预警阻塞，可直接进入库存平衡判断。"
        summary = (
            f"一、分析结论：申请需求 {demand}，可用量 {available}（库存 {summary.get('stock_qty', 0)} + 在途 {in_transit} - 预留 {reserve}），"
            f"安全库存 {safety}；采购建议 {purchase_qty}，调剂候选 {len(transfer_rows)} 条，预警 {len(warnings)} 条。\n"
            f"二、平衡利库策略：{balance_strategy}\n"
            f"三、执行顺序：1）{warning_step} 2）核对在途合同和预留工单；3）优先调剂，再决定采购；4）执行后刷新库存和预测。\n"
            "四、复核条件：若实际到货、需求预测或预留量发生变化，应重新运行分析，不沿用本次结论。"
        )
        return {"inventory": inventory_analysis, "purchase": purchase_analysis, "transfers": transfer_analysis, "forecast": forecast_analysis, "price": price_analysis, "warnings": warning_analysis, "summary": summary}

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
        if kind == "平衡利库工作台综合解读":
            inventory = data.get("inventory_balance") or {}
            summary = inventory.get("summary") or {}
            conclusion = inventory.get("conclusion") or {}
            item = inventory.get("item") or {}
            name = f"{item.get('ITEMNUM', '')} {item.get('DESCRIPTION', '')}".strip() or "该物料"
            inventory_text = (
                f"{name}：库存面板结论为库存 {summary.get('stock_qty', 0)}、在途 {summary.get('in_transit_qty', 0)}、"
                f"预留 {summary.get('reserved_qty', 0)}、安全库存 {summary.get('safety_stock_qty', 0)}、"
                f"可用量 {summary.get('available_qty', 0)}。{conclusion.get('text', '')}"
            )
            purchase = data.get("purchase_recommendation") or {}
            purchase_text = (
                f"采购建议：{purchase.get('warehouse_id', '目标仓库')} 建议采购 {purchase.get('purchase_quantity', 0)}，"
                f"预测需求 {purchase.get('forecast_demand', 0)}，采购时机 {purchase.get('timing_signal', '暂无')}。"
            )
            transfer_rows = data.get("transfer_recommendations") or []
            transfer_text = f"利库调剂：当前有 {len(transfer_rows)} 条候选。"
            forecast = data.get("demand_forecast") or {}
            forecast_text = f"需求预测：{forecast.get('pattern', '暂无历史')}，模型 {forecast.get('model_name', 'none')}，未来预测 {forecast.get('next_values', [])}。"
            price = data.get("price_timing") or {}
            price_text = f"价格择时：趋势 {price.get('direction', '暂无')}，{price.get('signal', '暂无')}，预计节省 {price.get('expected_saving', 0)}。"
            warnings = data.get("warnings") or []
            warning_text = f"预警中心：当前 {len(warnings)} 条预警。"
            if warnings:
                warning_text += "重点：" + "；".join(str(row.get("message") or row.get("warning_type") or "风险") for row in warnings[:3]) + "。"
            return "\n".join([inventory_text, purchase_text, transfer_text, forecast_text, price_text, warning_text])
        return "已根据业务数据生成分析结果。"
