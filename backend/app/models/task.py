from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[TaskStatus] = mapped_column(String(20), default=TaskStatus.PENDING)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def transition(self, target: TaskStatus) -> None:
        allowed = {
            TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
            TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
            TaskStatus.COMPLETED: set(),
            TaskStatus.FAILED: set(),
            TaskStatus.CANCELLED: set(),
        }
        current = self.status or TaskStatus.PENDING
        if target not in allowed[current]:
            raise ValueError(f"invalid task transition: {current} -> {target}")
        self.status = target
