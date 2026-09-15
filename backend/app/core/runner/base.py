from abc import ABC, abstractmethod
from typing import Any


class TaskRunner(ABC):
    @abstractmethod
    async def run(self, task_id: str, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_progress(self, task_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def is_running(self, task_id: str) -> bool:
        raise NotImplementedError

