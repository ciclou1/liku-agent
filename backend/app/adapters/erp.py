"""Read-only Jimu/Maximo ERP adapter for the balance-of-inventory workflow."""

from collections.abc import Iterable
from typing import Any

from app.adapters.base import DataAdapter
from app.core.config import get_settings
from app.erp.client import ErpClient


class JimuErpAdapter(DataAdapter):
    """Adapter SPI implementation backed by the ERP MySQL read channel.

    The adapter never writes to ERP or the local business database. Its load
    method is intentionally a no-op; balance analysis reads ERP on demand.
    """

    name = "jimu_erp"
    label = "积木 ERP（只读直连）"

    def __init__(self, client: ErpClient | None = None) -> None:
        self.client = client or ErpClient()
        self.connected = False

    def connect(self) -> None:
        if not self.client.ping():
            raise RuntimeError("积木 ERP 不可达，请检查 ERP_DB_* 配置与网络")
        self.connected = True

    def extract(self, since: str | None = None) -> Iterable[dict[str, Any]]:
        if not self.connected:
            self.connect()
        site = get_settings().erp_site_id
        return self.client.fetch_all(
            "SELECT b.ITEMNUM AS sku, b.LOCATION AS warehouse_id, "
            "SUM(COALESCE(b.CURBAL, 0)) AS available_quantity "
            "FROM invbalances b WHERE b.SITEID = %s AND COALESCE(b.IS_DEL, 0) = 0 "
            "GROUP BY b.ITEMNUM, b.LOCATION",
            [site], limit=100_000,
        )

    def transform(self, rows: Iterable[dict[str, Any]], mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def load(self, rows: Iterable[dict[str, Any]]) -> int:
        # ERP remains the source of truth; loading is intentionally read-only.
        return len(list(rows))

    def status(self) -> dict[str, Any]:
        ok = self.client.ping()
        return {"name": self.name, "label": self.label, "ok": ok,
                "site_id": get_settings().erp_site_id,
                "read_only": True}
