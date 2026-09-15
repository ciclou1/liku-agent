from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import AuditLog


class AuditPersistenceService:
    async def record(self, session: AsyncSession, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        event = AuditLog(id=str(uuid4()), actor=actor, action=action, resource=resource, detail=detail or {}, created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        session.add(event)
        await session.commit()
        return {"id": event.id, "actor": event.actor, "action": event.action, "resource": event.resource, "detail": event.detail, "created_at": event.created_at.isoformat()}

    async def list(self, session: AsyncSession) -> list[dict[str, Any]]:
        rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()))).scalars().all()
        return [{"id": row.id, "actor": row.actor, "action": row.action, "resource": row.resource, "detail": row.detail, "created_at": row.created_at.isoformat()} for row in rows]
