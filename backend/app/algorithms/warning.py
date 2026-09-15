from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class WarningLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class WarningType(StrEnum):
    STAGNANT = "stagnant"
    OVERSTOCK = "overstock"
    EXPIRING = "expiring"


@dataclass(frozen=True)
class WarningResult:
    sku: str
    warehouse_id: str
    warning_type: WarningType
    level: WarningLevel
    message: str
    action: str
    amount: float


def detect_warnings(item: dict, today: date, stagnant_days: int = 365, expiry_days: int = 90) -> list[WarningResult]:
    result: list[WarningResult] = []
    last_used = item.get("last_used_at")
    if last_used and (today - last_used).days >= stagnant_days and item.get("available_quantity", 0) > 0:
        amount = float(item.get("available_quantity", 0)) * float(item.get("unit_cost", 0))
        level = WarningLevel.CRITICAL if (today - last_used).days >= stagnant_days * 2 else WarningLevel.WARNING
        result.append(WarningResult(item["sku"], item["warehouse_id"], WarningType.STAGNANT, level, "长期无领用库存", "优先内部调剂，无法调剂时对外处置", amount))
    available = float(item.get("available_quantity", 0))
    safety = float(item.get("safety_stock", 0))
    if available > safety and safety >= 0:
        amount = (available - safety) * float(item.get("unit_cost", 0))
        result.append(WarningResult(item["sku"], item["warehouse_id"], WarningType.OVERSTOCK, WarningLevel.WARNING, "库存超过安全库存", "检查跨仓需求并生成调剂建议", amount))
    expiry = item.get("expiry_date")
    if expiry and 0 <= (expiry - today).days <= expiry_days and available > 0:
        level = WarningLevel.CRITICAL if (expiry - today).days <= 30 else WarningLevel.WARNING
        amount = available * float(item.get("unit_cost", 0))
        result.append(WarningResult(item["sku"], item["warehouse_id"], WarningType.EXPIRING, level, "物资临近质保期", "优先领用或内部调剂", amount))
    return result

