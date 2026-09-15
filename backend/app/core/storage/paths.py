from pathlib import Path

from app.core.config import get_settings


class StoragePaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(get_settings().storage_path)

    def ensure(self) -> None:
        for path in (self.root, self.datasets(), self.exports(), self.tasks(), self.runs(), self.models(), self.uploads()):
            path.mkdir(parents=True, exist_ok=True)
        for path in (self.uploads() / "datasets", self.uploads() / "models", self.uploads() / "images"):
            path.mkdir(parents=True, exist_ok=True)

    def datasets(self) -> Path:
        return self.root / "datasets"

    def exports(self) -> Path:
        return self.root / "exports"

    def tasks(self) -> Path:
        return self.root / "tasks"

    def runs(self) -> Path:
        return self.root / "runs"

    def models(self) -> Path:
        return self.root / "models"

    def uploads(self) -> Path:
        return self.root / "uploads"

    def task_dir(self, task_id: str) -> Path:
        path = self.tasks() / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def task_config(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "config.json"

    def task_pid(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "pid"

    def task_progress(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "progress.json"

    def task_result(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "result.json"

