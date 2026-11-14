"""Local, bounded observations of screens; no screenshots or raw titles are stored."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import sqlite3
import time


class ScreenMemory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                category TEXT NOT NULL, summary TEXT NOT NULL,
                seen_count INTEGER NOT NULL, first_seen REAL NOT NULL,
                last_seen REAL NOT NULL, PRIMARY KEY (category, summary))""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, category: str, summary: str):
        if not category or not summary or len(summary) > 80:
            return
        now = time.time()
        with self._connect() as db:
            db.execute("""INSERT INTO observations VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(category, summary) DO UPDATE SET
                seen_count=seen_count+1, last_seen=excluded.last_seen""",
                (category, summary, now, now))
            db.execute("""DELETE FROM observations WHERE rowid IN
                (SELECT rowid FROM observations ORDER BY last_seen DESC LIMIT -1 OFFSET 200)""")

    def recent(self, category: str, limit: int = 3) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""SELECT summary, seen_count FROM observations
                WHERE category=? ORDER BY last_seen DESC LIMIT ?""",
                (category, min(limit, 3))).fetchall()
        return [{"summary": summary, "seen_count": count} for summary, count in rows]

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

