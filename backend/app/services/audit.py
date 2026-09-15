from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.operations import AuditLog


class AuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"id": str(uuid4()), "actor": actor, "action": action, "resource": resource, "detail": detail or {}, "created_at": datetime.now(timezone.utc).isoformat()}
        self.events.append(event)
        return event

    def model(self, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> AuditLog:
        event = self.record(actor, action, resource, detail)
        return AuditLog(id=event["id"], actor=actor, action=action, resource=resource, detail=event["detail"], created_at=datetime.fromisoformat(event["created_at"]))

