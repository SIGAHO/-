from __future__ import annotations
import json
import os
from pathlib import Path
from .models import Event, SourceType
from .ownership import LogLease


class EventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[Event] = []
        self._size = 0
        if self.path:
            with LogLease(str(self.path) + ".append"):
                if self.path.exists():
                    self._load()
                    self._size = self.path.stat().st_size

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
            with LogLease(str(self.path) + ".append"):
                size = self.path.stat().st_size if self.path.exists() else 0
                if size != self._size:
                    raise OSError("ログが別の書き込み元により変更されました。daemon経由で再接続してください")
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                    self._size = self.path.stat().st_size
        self.events.append(event)
