from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .timeline_item import TimelineItem

PROJECT_VERSION = 1
PROJECT_EXTENSION = ".sasproj"


@dataclass
class Project:
    name: str = "Untitled Service"
    items: list[TimelineItem] = field(default_factory=list)
    file_path: str | None = None
    last_export_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROJECT_VERSION,
            "name": self.name,
            "last_export_path": self.last_export_path,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], file_path: str | None = None) -> Project:
        items = [TimelineItem.from_dict(item) for item in data.get("items", [])]
        return cls(
            name=data.get("name", "Untitled Service"),
            items=items,
            file_path=file_path,
            last_export_path=data.get("last_export_path"),
        )

    def save(self, path: str | None = None) -> None:
        target = Path(path or self.file_path or "")
        if not target:
            raise ValueError("No project file path specified.")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.file_path = str(target)

    @classmethod
    def load(cls, path: str) -> Project:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(f"Project file not found: {path}")
        data = json.loads(target.read_text(encoding="utf-8"))
        version = data.get("version", 1)
        if version != PROJECT_VERSION:
            raise ValueError(
                f"Unsupported project version {version}. "
                f"This app supports version {PROJECT_VERSION}."
            )
        return cls.from_dict(data, file_path=str(target))

    def missing_sources(self) -> list[TimelineItem]:
        return [item for item in self.items if not item.source_exists]
