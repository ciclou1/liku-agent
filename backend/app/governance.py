from collections.abc import Iterable
from typing import Any


def normalize_materials(rows: Iterable[dict[str, Any]], aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    aliases = aliases or {}
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_sku = str(row.get("sku", "")).strip()
        if not raw_sku:
            continue
        sku = aliases.get(raw_sku, raw_sku).upper()
        current = normalized.setdefault(sku, {"sku": sku, "aliases": []})
        if raw_sku != sku and raw_sku not in current["aliases"]:
            current["aliases"].append(raw_sku)
        current.update({key: value for key, value in row.items() if value not in (None, "") and key != "sku"})
        current["sku"] = sku
    return list(normalized.values())


def validate_numeric(row: dict[str, Any], fields: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for field in fields:
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            if float(value) < 0:
                errors.append(f"{field} must be non-negative")
        except (TypeError, ValueError):
            errors.append(f"{field} must be numeric")
    return errors

