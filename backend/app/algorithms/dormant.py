"""呆滞库存识别与处置建议算法（纯函数，无 IO）。

处置优先级（与业务确认口径一致）：
① 调剂 —— 其他仓库近 12 个月有领用，且现存量低于需求（安全库存；未设置时用该仓年领用量）
② 退货 —— 近 12 个月有采购入库/合同记录，建议与供应商协商退货
③ 报废评估 —— 其余长龄无消耗物资，按呆滞时长分档给出提示
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


TRANSFER = "调剂"
RETURN = "退货"
SCRAP = "报废评估"

_SUGGESTION_LABELS = {
    TRANSFER: "建议优先内部调剂",
    RETURN: "建议与供应商协商退货",
    SCRAP: "建议组织报废评估",
}


@dataclass(frozen=True)
class DisposalResult:
    sku: str
    warehouse_id: str
    suggestion: str
    basis: str
    amount: float
    days_idle: int | None

    @property
    def action(self) -> str:
        return _SUGGESTION_LABELS.get(self.suggestion, self.suggestion)


def _days_idle(last_used_at: date | None, today: date) -> int | None:
    if last_used_at is None:
        return None
    return max((today - last_used_at).days, 0)


def classify_disposal(row: dict, today: date) -> DisposalResult:
    """对单条呆滞库存行给出处置建议。

    row 必备字段：sku、warehouse_id、available_quantity、unit_cost、last_used_at；
    可选信号字段：has_transfer_demand(bool)、last_purchase(dict，含 date/supplier)。
    """
    quantity = float(row.get("available_quantity") or 0)
    unit_cost = float(row.get("unit_cost") or 0)
    amount = round(quantity * unit_cost, 2)
    idle = _days_idle(row.get("last_used_at"), today)

    if row.get("has_transfer_demand"):
        # 调用方只传库房字典里的名称；仍做一次兜底，避免脏编码（如 ERP 的 '{}'）落到文案里
        raw = str(row.get("demand_warehouse") or "").strip()
        demand_warehouse = raw if raw and raw not in ("{}", "None") else "其他仓库"
        basis = f"{demand_warehouse} 近 12 个月有领用且现存量低于需求，建议优先内部调剂"
        return DisposalResult(row["sku"], row["warehouse_id"], TRANSFER, basis, amount, idle)

    last_purchase = row.get("last_purchase")
    if isinstance(last_purchase, dict) and last_purchase.get("date"):
        supplier = str(last_purchase.get("supplier") or "供应商")
        basis = f"近 12 个月有采购记录（{last_purchase.get('date')}，{supplier}），建议与供应商协商退货"
        return DisposalResult(row["sku"], row["warehouse_id"], RETURN, basis, amount, idle)

    if idle is None:
        basis = "该库房从未发生领用，长龄无消耗，建议组织报废评估"
    elif idle >= 730:
        basis = f"已 {idle} 天无领用（超过两年），建议组织报废评估"
    else:
        basis = f"已 {idle} 天无领用且无调剂需求与近期采购，建议组织报废评估"
    return DisposalResult(row["sku"], row["warehouse_id"], SCRAP, basis, amount, idle)
