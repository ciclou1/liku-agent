from collections.abc import Iterable
from typing import Any

from app.adapters.base import DataAdapter
from app.adapters.generic import ApiAdapter, DatabaseAdapter, StagingTableAdapter, WebServiceAdapter
from app.adapters.market import MarketDataAdapter
from app.adapters.erp import JimuErpAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, DataAdapter] = {}

    def register(self, adapter: DataAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> DataAdapter:
        return self._adapters[name]

    def names(self) -> list[str]:
        return sorted(self._adapters)


adapter_registry = AdapterRegistry()
for adapter in (DatabaseAdapter("database"), ApiAdapter("api"), WebServiceAdapter("webservice"), StagingTableAdapter("staging"), MarketDataAdapter("market"), JimuErpAdapter()):
    adapter_registry.register(adapter)
