from dataclasses import dataclass


@dataclass(frozen=True)
class AccessContext:
    username: str
    role: str
    organization_id: str | None = None
    warehouse_ids: frozenset[str] = frozenset()

    def can(self, required_role: str) -> bool:
        hierarchy = {"worker": 1, "planner": 2, "manager": 3, "admin": 4}
        return hierarchy.get(self.role, 0) >= hierarchy.get(required_role, 99)

    def can_access_warehouse(self, warehouse_id: str) -> bool:
        return not self.warehouse_ids or warehouse_id in self.warehouse_ids

