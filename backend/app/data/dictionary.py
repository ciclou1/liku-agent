from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    data_type: str
    required: bool
    description: str


DATA_DICTIONARY: dict[str, tuple[FieldDefinition, ...]] = {
    "materials": (
        FieldDefinition("sku", "string", True, "物料唯一编码"),
        FieldDefinition("name", "string", True, "物料名称"),
        FieldDefinition("category", "string", False, "物料分类"),
        FieldDefinition("unit", "string", False, "计量单位"),
        FieldDefinition("package_size", "decimal", True, "最小包装规格"),
    ),
    "procurement_orders": (
        FieldDefinition("sku", "string", True, "物料编码"),
        FieldDefinition("warehouse_id", "string", True, "收货仓库"),
        FieldDefinition("supplier", "string", True, "供应商"),
        FieldDefinition("quantity", "decimal", True, "采购数量"),
        FieldDefinition("unit_price", "decimal", True, "采购单价"),
        FieldDefinition("ordered_at", "date", True, "下单日期"),
    ),
    "usage_records": (
        FieldDefinition("sku", "string", True, "物料编码"),
        FieldDefinition("warehouse_id", "string", True, "领用仓库"),
        FieldDefinition("quantity", "decimal", True, "领用数量"),
        FieldDefinition("used_at", "date", True, "领用日期"),
    ),
    "inventory_snapshots": (
        FieldDefinition("sku", "string", True, "物料编码"),
        FieldDefinition("warehouse_id", "string", True, "库存仓库"),
        FieldDefinition("available_quantity", "decimal", True, "可用库存"),
        FieldDefinition("in_transit_quantity", "decimal", False, "在途数量"),
        FieldDefinition("unit_cost", "decimal", False, "库存成本"),
        FieldDefinition("expiry_date", "date", False, "质保到期日"),
    ),
    "price_records": (
        FieldDefinition("sku", "string", True, "物料编码"),
        FieldDefinition("supplier", "string", True, "供应商"),
        FieldDefinition("price", "decimal", True, "报价"),
        FieldDefinition("recorded_at", "date", True, "报价日期"),
    ),
}


def required_fields(entity: str) -> set[str]:
    return {field.name for field in DATA_DICTIONARY[entity] if field.required}

