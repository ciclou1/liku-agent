import json
from pathlib import Path

import pytest

from app.core.runner.local import LocalTaskRunner
from app.core.storage.paths import StoragePaths
from app.models.task import TaskStatus


def test_task_state_machine() -> None:
    from app.models.task import Task

    task = Task(task_type="fixture")
    task.transition(TaskStatus.RUNNING)
    task.transition(TaskStatus.COMPLETED)
    with pytest.raises(ValueError):
        task.transition(TaskStatus.RUNNING)


@pytest.mark.asyncio
async def test_local_runner_writes_required_worker_files(tmp_path: Path) -> None:
    runner = LocalTaskRunner(StoragePaths(tmp_path))
    result = await runner.run("task-1", {"mode": "fixture"})
    assert result["status"] == "completed"
    assert await runner.get_progress("task-1") == 100
    assert await runner.get_result("task-1") == result
    assert json.loads((tmp_path / "tasks" / "task-1" / "config.json").read_text()) == {"mode": "fixture"}

