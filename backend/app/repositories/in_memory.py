from collections.abc import Iterable
from typing import Any


class InMemoryRepository:
    def __init__(self, rows: Iterable[dict[str, Any]] = ()) -> None:
        self.rows = list(rows)

    def list(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        return [row for row in self.rows if all(value is None or row.get(key) == value for key, value in filters.items())]

    def add(self, row: dict[str, Any]) -> dict[str, Any]:
        self.rows.append(row)
        return row

