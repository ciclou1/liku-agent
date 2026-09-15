from collections.abc import Iterable
from io import BytesIO

from openpyxl import Workbook

from app.models.operations import RecommendationStatus


class RecommendationService:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, row: dict) -> dict:
        item = {**row, "id": str(len(self.rows) + 1), "status": RecommendationStatus.GENERATED}
        self.rows.append(item)
        return item

    def list(self) -> list[dict]:
        return list(self.rows)

    def transition(self, item_id: str, target: str) -> dict:
        item = next((row for row in self.rows if row["id"] == item_id), None)
        if item is None:
            raise ValueError("采购建议不存在")
        current = item["status"]
        allowed = {
            RecommendationStatus.GENERATED: {RecommendationStatus.REVIEWED},
            RecommendationStatus.REVIEWED: {RecommendationStatus.EXPORTED, RecommendationStatus.PUSHED},
            RecommendationStatus.EXPORTED: {RecommendationStatus.PUSHED},
            RecommendationStatus.PUSHED: set(),
        }
        if target not in allowed[current]:
            raise ValueError(f"invalid recommendation transition: {current} -> {target}")
        item["status"] = target
        return item

    def update_review(self, item_id: str, status: str | None = None, purchase_quantity: float | None = None) -> dict:
        item = next((row for row in self.rows if row["id"] == item_id), None)
        if item is None:
            raise ValueError("采购建议不存在")
        if purchase_quantity is not None:
            item["purchase_quantity"] = purchase_quantity
            item["calculation_basis"]["reviewed_quantity"] = purchase_quantity
        if status is not None:
            return self.transition(item_id, status)
        return item

    def export_xlsx(self, rows: Iterable[dict] | None = None) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["SKU", "品类", "建议采购量", "择时信号", "状态", "预期节省"])
        for row in rows or self.rows:
            sheet.append([row.get("sku"), row.get("category"), row.get("purchase_quantity"), row.get("timing_signal"), row.get("status"), row.get("expected_saving", 0)])
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()
