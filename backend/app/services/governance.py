from collections.abc import Iterable
from typing import Any

from app.governance import normalize_materials, validate_numeric


class DataGovernanceService:
    def clean_materials(self, rows: Iterable[dict[str, Any]], aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return normalize_materials(rows, aliases)

    def validate_rows(self, rows: Iterable[dict[str, Any]], numeric_fields: Iterable[str]) -> dict[str, Any]:
        valid: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            row_errors = validate_numeric(row, numeric_fields)
            if row_errors:
                errors.append({"row": index, "errors": row_errors})
            else:
                valid.append(dict(row))
        return {"valid": valid, "errors": errors, "missing_count": sum(any(value in (None, "") for value in row.values()) for row in valid)}

