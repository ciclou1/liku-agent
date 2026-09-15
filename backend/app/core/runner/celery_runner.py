import json
from typing import Any
from uuid import uuid4

from app.core.runner.base import TaskRunner
from app.core.storage.backend import StorageBackend
from app.core.storage.paths import StoragePaths


class CeleryTaskRunner(TaskRunner):
    def __init__(self, paths: StoragePaths | None = None) -> None:
        self.paths = paths or StoragePaths()
        self.storage = StorageBackend()
        self.task_ids: dict[str, str] = {}

    async def run(self, task_id: str, config: dict[str, Any]) -> dict[str, Any]:
        from app.celery_app import execute_task

        self.storage.write_text(self.paths.task_config(task_id), json.dumps(config, ensure_ascii=False))
        self.storage.write_text(self.paths.task_progress(task_id), json.dumps({"progress": 0}))
        celery_id = str(uuid4())
        self.task_ids[task_id] = celery_id
        execute_task.apply_async(args=[task_id], task_id=celery_id)
        return {"pid": celery_id, "task_id": celery_id, "status": "pending"}

    async def cancel(self, task_id: str) -> None:
        from app.celery_app import celery_app

        celery_id = self.task_ids.get(task_id)
        if celery_id:
            celery_app.control.revoke(celery_id, terminate=False)
        self.storage.write_text(self.paths.task_progress(task_id), json.dumps({"progress": 0, "cancelled": True}))

    async def get_progress(self, task_id: str) -> int:
        path = self.paths.task_progress(task_id)
        if not path.exists():
            return 0
        return int(json.loads(path.read_text(encoding="utf-8")).get("progress", 0))

    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        path = self.paths.task_result(task_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    async def is_running(self, task_id: str) -> bool:
        return await self.get_result(task_id) is None and await self.get_progress(task_id) < 100
