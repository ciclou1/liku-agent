from datetime import date

from app.algorithms.warning import detect_warnings
from app.data.fixtures import inventory_fixture
from app.im import ImMessage, ImProvider
from app.services.configuration import WarningRuleConfig


class WarningService:
    def __init__(self) -> None:
        self.rules: dict[str, WarningRuleConfig] = {
            "stagnant": WarningRuleConfig("stagnant", 365, "warning"),
            "overstock": WarningRuleConfig("overstock", 1.0, "warning"),
            "expiring": WarningRuleConfig("expiring", 90, "warning"),
        }

    def configure_rule(self, config: WarningRuleConfig) -> WarningRuleConfig:
        self.rules[config.warning_type] = config
        return config

    def list(self) -> list[dict]:
        stagnant_days = int(self.rules["stagnant"].threshold)
        expiry_days = int(self.rules["expiring"].threshold)
        warnings = [warning for row in inventory_fixture() for warning in detect_warnings(row, date(2026, 9, 8), stagnant_days=stagnant_days, expiry_days=expiry_days)]
        unique: dict[tuple[str, str, str], dict] = {}
        for warning in warnings:
            rule = self.rules.get(warning.warning_type.value)
            if rule and not rule.enabled:
                continue
            unique[(warning.sku, warning.warehouse_id, warning.warning_type.value)] = {**warning.__dict__, "warning_type": warning.warning_type.value, "level": rule.level if rule else warning.level.value}
        return list(unique.values())

    async def push(self, provider: ImProvider, recipient: str = "demo-user") -> dict[str, int | str]:
        warnings = self.list()
        for item in warnings:
            message = ImMessage("warning", f"{item['sku']} 风险预警", f"{item['message']}；建议：{item['action']}")
            await provider.send_text(recipient, message)
        return {"platform": provider.platform, "count": len(warnings), "status": "sent"}
