from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


class DataAdapter(ABC):
    name: str

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def extract(self, since: str | None = None) -> Iterable[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def transform(self, rows: Iterable[dict[str, Any]], mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def load(self, rows: Iterable[dict[str, Any]]) -> int:
        raise NotImplementedError

    def sync(self, since: str | None = None, mapping: dict[str, str] | None = None) -> int:
        self.connect()
        rows = self.transform(self.extract(since), mapping)
        return self.load(rows)

