from collections.abc import Iterable
from typing import Any

import httpx

from xml.etree import ElementTree

from app.adapters.base import DataAdapter


class GenericAdapter(DataAdapter):
    def __init__(self, name: str, rows: Iterable[dict[str, Any]] = ()) -> None:
        self.name = name
        self.rows = list(rows)
        self.loaded_rows: list[dict[str, Any]] = []
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def extract(self, since: str | None = None) -> Iterable[dict[str, Any]]:
        return self.rows

    def transform(self, rows: Iterable[dict[str, Any]], mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
        mapping = mapping or {}
        return [{mapping.get(key, key): value for key, value in row.items()} for row in rows]

    def load(self, rows: Iterable[dict[str, Any]]) -> int:
        self.loaded_rows = list(rows)
        return len(self.loaded_rows)


class DatabaseAdapter(GenericAdapter):
    def __init__(self, name: str = "database", rows: Iterable[dict[str, Any]] = (), query: str | None = None) -> None:
        super().__init__(name, rows)
        self.query = query

    def extract(self, since: str | None = None) -> Iterable[dict[str, Any]]:
        return self.rows


class ApiAdapter(GenericAdapter):
    def __init__(self, name: str = "api", rows: Iterable[dict[str, Any]] = (), endpoint: str | None = None) -> None:
        super().__init__(name, rows)
        self.endpoint = endpoint

    def extract(self, since: str | None = None) -> Iterable[dict[str, Any]]:
        if not self.endpoint:
            return self.rows
        response = httpx.get(self.endpoint, params={"since": since} if since else None, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


class WebServiceAdapter(GenericAdapter):
    def __init__(self, name: str = "webservice", rows: Iterable[dict[str, Any]] = (), operation: str | None = None) -> None:
        super().__init__(name, rows)
        self.operation = operation

    def parse_response(self, xml_payload: str) -> list[dict[str, Any]]:
        root = ElementTree.fromstring(xml_payload)
        return [{child.tag: child.text for child in item} for item in root.findall(".//record")]


class StagingTableAdapter(GenericAdapter):
    def __init__(self, name: str = "staging", rows: Iterable[dict[str, Any]] = ()) -> None:
        super().__init__(name, rows)
        self.staged_rows = self.rows
