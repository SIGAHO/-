from __future__ import annotations
import json
import os
from pathlib import Path
from .models import Event, SourceType


class EventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[Event] = []
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Event log {self.path}, line {number}: invalid JSON; preserve and repair the log before restarting") from exc
            self.events.append(Event(
                id=d["id"], kind=d["kind"], payload=d["payload"],
                source=SourceType(d["source"]), ts=d["ts"]
            ))

    def append(self, event: Event) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        self.events.append(event)
