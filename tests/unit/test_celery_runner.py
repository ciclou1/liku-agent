from pathlib import Path

import pytest

from app.core.runner.celery_runner import CeleryTaskRunner
from app.core.storage.paths import StoragePaths


@pytest.mark.asyncio
async def test_celery_runner_writes_config_before_enqueue(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeTask:
        def apply_async(self, args: list[str], task_id: str) -> None:
            captured["args"] = args
            captured["task_id"] = task_id

    class FakeModule:
        execute_task = FakeTask()

    monkeypatch.setitem(__import__("sys").modules, "app.celery_app", FakeModule())
    runner = CeleryTaskRunner(StoragePaths(tmp_path))
    result = await runner.run("task-1", {"task_type": "sync"})
    assert result["status"] == "pending"
    assert captured["args"] == ["task-1"]
    assert (tmp_path / "tasks" / "task-1" / "config.json").exists()
