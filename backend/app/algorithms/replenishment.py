"""安全库存优化算法（纯函数，无 IO）。

按月度消耗速率（均值 μ、标准差 σ）与供应交期 L（月）计算：
- 建议安全库存 = z × σ × √L（z 默认 1.65，约 95% 服务水平）
- 补货点 ROP = μ × L + z × σ × √L（消耗期库存 + 安全库存）
- 建议补货量 = ceil(max(0, μ × 覆盖月数 − 可用量 − 在途量) / 最小包装) × 最小包装
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, sqrt
from statistics import stdev

# 有消耗月份不足该数时判定为数据不足（预测无意义）
MIN_MONTHS = 3
# 计算月均/波动所用的回看窗口（月）
LOOKBACK_MONTHS = 12


@dataclass(frozen=True)
class ReplenishmentResult:
    mu_monthly: float
    sigma_monthly: float
    lead_time_months: float
    service_level_z: float
    suggested_safety: float
    reorder_point: float
    reorder_quantity: float
    current_safety: float
    safety_gap: float
    coverage_months: float
    months_used: int
    formula_explanation: dict[str, str] = field(default_factory=dict)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def optimize_replenishment(
    monthly_usage: list[float],
    lead_time_months: float,
    current_safety: float,
    available: float,
    in_transit: float,
    package_size: float = 1.0,
    z: float = 1.65,
    coverage_months: float = 3.0,
) -> ReplenishmentResult | None:
    """输入近 N 月逐月消耗序列（0 月也计入，体现间歇性），输出补货建议。

    数据不足（有记录月份 < MIN_MONTHS）返回 None，由调用方提示补数据。
    """
    if lead_time_months <= 0:
        lead_time_months = 1.0
    usage = [float(value or 0) for value in monthly_usage[-LOOKBACK_MONTHS:]]
    if len(usage) < MIN_MONTHS:
        return None
    mu = sum(usage) / len(usage)
    sigma = stdev(usage) if len(usage) > 1 else 0.0
    window = z * sigma * sqrt(lead_time_months)
    suggested_safety = _round(window)
    reorder_point = _round(mu * lead_time_months + window)
    package = max(float(package_size or 1), 1e-9)
    raw_need = mu * coverage_months - float(available or 0) - float(in_transit or 0)
    units = max(0.0, raw_need)
    reorder_quantity = _round(ceil(units / package) * package)
    return ReplenishmentResult(
        mu_monthly=_round(mu, 4),
        sigma_monthly=_round(sigma, 4),
        lead_time_months=_round(lead_time_months, 2),
        service_level_z=z,
        suggested_safety=suggested_safety,
        reorder_point=reorder_point,
        reorder_quantity=reorder_quantity,
        current_safety=_round(current_safety, 4),
        safety_gap=_round(suggested_safety - float(current_safety or 0), 2),
        coverage_months=coverage_months,
        months_used=len(usage),
        formula_explanation={
            "safety": "建议安全库存 = z × σ × √L（z=1.65，约 95% 服务水平；σ 为月消耗波动，L 为供应交期月数）",
            "reorder_point": "补货点 = μ × L + z × σ × √L（交期消耗 + 安全库存，库存降至该点应触发补货）",
            "reorder_quantity": "建议补货量 = 向上取整[(μ × 覆盖月数 − 可用量 − 在途量) / 最小包装] × 最小包装",
            "consumption": "μ/σ 取近 12 个月逐月领用量（含零消耗月，体现备件间歇性）",
        },
    )
