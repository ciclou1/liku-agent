from typing import Any
from uuid import uuid4

from app.core.runner.local import LocalTaskRunner
from app.core.runner.celery_runner import CeleryTaskRunner
from app.core.config import get_settings
from app.models.task import TaskStatus


class TaskService:
    def __init__(self) -> None:
        self.runner = LocalTaskRunner() if get_settings().app_env == "test" else CeleryTaskRunner()
        self.tasks: dict[str, dict[str, Any]] = {}

    async def create_and_run(self, task_type: str, config: dict[str, Any]) -> dict[str, Any]:
        task_id = str(uuid4())
        self.tasks[task_id] = {"id": task_id, "task_type": task_type, "status": TaskStatus.PENDING.value, "config": config}
        result = await self.runner.run(task_id, {**config, "task_type": task_type})
        self.tasks[task_id].update({"status": result.get("status", TaskStatus.PENDING.value), "result": result, "progress": 100 if result.get("status") == "completed" else 0})
        return self.tasks[task_id]

    async def get(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if task:
            task["progress"] = await self.runner.get_progress(task_id)
            result = await self.runner.get_result(task_id)
            if result:
                task["result"] = result
                task["status"] = result.get("status", task["status"])
        return task

    async def cancel(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if not task or task["status"] in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
            return task
        await self.runner.cancel(task_id)
        task["status"] = TaskStatus.CANCELLED.value
        return task
