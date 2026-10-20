from __future__ import annotations
import json
from pathlib import Path
from .models import Event, SourceType


class EventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[Event] = []
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            self.events.append(Event(
                id=d["id"], kind=d["kind"], payload=d["payload"],
                source=SourceType(d["source"]), ts=d["ts"]
            ))

    def append(self, event: Event) -> None:
        self.events.append(event)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
