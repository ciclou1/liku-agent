import json
import os
from typing import Any

from app.core.runner.base import TaskRunner
from app.core.storage.paths import StoragePaths


class LocalTaskRunner(TaskRunner):
    def __init__(self, paths: StoragePaths | None = None) -> None:
        self.paths = paths or StoragePaths()

    async def run(self, task_id: str, config: dict[str, Any]) -> dict[str, Any]:
        self.paths.task_pid(task_id).write_text(str(os.getpid()), encoding="utf-8")
        self.paths.task_config(task_id).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.paths.task_progress(task_id).write_text(json.dumps({"progress": 100}), encoding="utf-8")
        result = {"pid": os.getpid(), "status": "completed"}
        self.paths.task_result(task_id).write_text(json.dumps(result), encoding="utf-8")
        return result

    async def cancel(self, task_id: str) -> None:
        self.paths.task_progress(task_id).write_text(json.dumps({"progress": 0, "cancelled": True}), encoding="utf-8")

    async def get_progress(self, task_id: str) -> int:
        path = self.paths.task_progress(task_id)
        if not path.exists():
            return 0
        return int(json.loads(path.read_text(encoding="utf-8")).get("progress", 0))

    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        path = self.paths.task_result(task_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    async def is_running(self, task_id: str) -> bool:
        return (await self.get_result(task_id)) is None and self.paths.task_pid(task_id).exists()
