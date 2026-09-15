from dataclasses import dataclass, field


@dataclass
class SafetyStockConfig:
    category: str
    quantity: float
    service_level: float = 0.95


@dataclass
class WarningRuleConfig:
    warning_type: str
    threshold: float
    level: str
    scope: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class ConfigurationService:
    def __init__(self) -> None:
        self.safety_stock: dict[str, SafetyStockConfig] = {}
        self.warning_rules: dict[str, WarningRuleConfig] = {}
        self.price_targets: set[str] = set()

    def set_safety_stock(self, config: SafetyStockConfig) -> SafetyStockConfig:
        self.safety_stock[config.category] = config
        return config

    def set_warning_rule(self, config: WarningRuleConfig) -> WarningRuleConfig:
        self.warning_rules[config.warning_type] = config
        return config

    def get_warning_rule(self, warning_type: str) -> WarningRuleConfig | None:
        return self.warning_rules.get(warning_type)

    def set_price_target(self, sku: str, enabled: bool = True) -> bool:
        if enabled:
            self.price_targets.add(sku)
        else:
            self.price_targets.discard(sku)
        return enabled
