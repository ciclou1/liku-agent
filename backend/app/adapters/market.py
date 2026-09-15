from collections.abc import Iterable
from typing import Any

from app.adapters.generic import GenericAdapter


class MarketDataAdapter(GenericAdapter):
    """行情服务商只需实现同一行式契约即可接入。"""

    def get_prices(self, sku: str) -> list[float]:
        return [float(row["price"]) for row in self.rows if row.get("sku") == sku]

