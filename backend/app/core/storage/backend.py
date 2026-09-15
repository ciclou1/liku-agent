from pathlib import Path


class StorageBackend:
    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_text(self, path: Path) -> str | None:
        return path.read_text(encoding="utf-8") if path.exists() else None

    def delete(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def delete_dir(self, path: Path) -> None:
        if path.exists():
            for child in path.iterdir():
                if child.is_dir():
                    self.delete_dir(child)
                else:
                    child.unlink()
            path.rmdir()

