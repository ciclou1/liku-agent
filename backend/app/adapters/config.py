import json
from pathlib import Path

from app.exceptions import ValidationError


class MappingConfig:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    @classmethod
    def load(cls, path: Path) -> "MappingConfig":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("字段映射配置不可读取") from exc
        if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
            raise ValidationError("字段映射配置必须是字符串键值对")
        return cls(data)

    def apply(self, row: dict[str, object]) -> dict[str, object]:
        return {self.values.get(key, key): value for key, value in row.items()}

