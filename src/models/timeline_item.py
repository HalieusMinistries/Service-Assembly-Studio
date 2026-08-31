from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ItemType(str, Enum):
    SPEECH = "speech"
    WORSHIP = "worship"


@dataclass
class TimelineItem:
    source_path: str
    display_name: str
    item_type: ItemType = ItemType.SPEECH
    trim_start: float = 0.0
    trim_end: float | None = None
    duration: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def effective_duration(self) -> float:
        end = self.trim_end if self.trim_end is not None else self.duration
        return max(0.0, end - self.trim_start)

    @property
    def source_exists(self) -> bool:
        return Path(self.source_path).is_file()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_path": self.source_path,
            "display_name": self.display_name,
            "item_type": self.item_type.value,
            "trim_start": self.trim_start,
            "trim_end": self.trim_end,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelineItem:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            source_path=data["source_path"],
            display_name=data["display_name"],
            item_type=ItemType(data.get("item_type", ItemType.SPEECH.value)),
            trim_start=float(data.get("trim_start", 0.0)),
            trim_end=data.get("trim_end"),
            duration=float(data.get("duration", 0.0)),
        )
