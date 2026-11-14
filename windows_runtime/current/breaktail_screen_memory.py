"""Local, bounded observations of screens; no screenshots or raw titles are stored."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from io import BytesIO
import sqlite3
import time

from PIL import Image


def visual_signature(jpeg: bytes) -> str:
    """Compact visual clue, never a reversible screenshot."""
    image = Image.open(BytesIO(jpeg)).convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = image.tobytes()
    average = sum(pixels) / len(pixels)
    bits = sum((pixel >= average) << index for index, pixel in enumerate(pixels))
    return f"{int(average):02x}{bits:016x}"


def signature_distance(left: str, right: str) -> int:
    if abs(int(left[:2], 16) - int(right[:2], 16)) > 25:
        return 65
    return (int(left[2:], 16) ^ int(right[2:], 16)).bit_count()


class ScreenMemory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                category TEXT NOT NULL, summary TEXT NOT NULL,
                seen_count INTEGER NOT NULL, first_seen REAL NOT NULL,
                last_seen REAL NOT NULL, PRIMARY KEY (category, summary))""")
            db.execute("""CREATE TABLE IF NOT EXISTS scene_observations (
                id INTEGER PRIMARY KEY, category TEXT NOT NULL,
                visual_signature TEXT NOT NULL, summary TEXT NOT NULL,
                seen_count INTEGER NOT NULL, first_seen REAL NOT NULL,
                last_seen REAL NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS scene_category_recent
                ON scene_observations(category, last_seen DESC)""")
            db.execute("""CREATE TABLE IF NOT EXISTS wiki_references (
                term TEXT PRIMARY KEY, title TEXT NOT NULL, excerpt TEXT NOT NULL,
                url TEXT NOT NULL, checked_at REAL NOT NULL)""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, category: str, summary: str, signature: str):
        if not category or not summary or len(summary) > 80 or len(signature) != 18:
            return
        now = time.time()
        with self._connect() as db:
            candidates = db.execute("""SELECT id, visual_signature FROM scene_observations
                WHERE category=? AND summary=? ORDER BY last_seen DESC LIMIT 100""",
                (category, summary)).fetchall()
            nearest = min(candidates, key=lambda row: signature_distance(signature, row[1]),
                          default=None)
            if nearest and signature_distance(signature, nearest[1]) <= 6:
                db.execute("""UPDATE scene_observations SET seen_count=seen_count+1,
                    last_seen=? WHERE id=?""", (now, nearest[0]))
            elif db.execute("SELECT COUNT(*) FROM scene_observations").fetchone()[0] < 2000:
                db.execute("""INSERT INTO scene_observations
                    (category, visual_signature, summary, seen_count, first_seen, last_seen)
                    VALUES (?, ?, ?, 1, ?, ?)""", (category, signature, summary, now, now))

    def recent(self, category: str, signature: str, limit: int = 3) -> list[dict]:
        if len(signature) != 18:
            return []
        with self._connect() as db:
            rows = db.execute("""SELECT summary, seen_count, visual_signature, last_seen
                FROM scene_observations WHERE category=? ORDER BY last_seen DESC LIMIT 2000""",
                (category,)).fetchall()
        matches = [(signature_distance(signature, row[2]), *row) for row in rows]
        matches = [row for row in matches if row[0] <= 6]
        matches.sort(key=lambda row: (row[0], -row[2], -row[4]))
        return [{"summary": summary, "seen_count": count, "distance": distance,
                 "last_seen": seen} for distance, summary, count, _, seen
                in matches[:max(0, min(limit, 3))]]

    def legacy_recent(self, category: str) -> list[dict]:
        """Old coarse records remain available to the user, but not injected into vision."""
        with self._connect() as db:
            rows = db.execute("""SELECT summary, seen_count FROM observations
                WHERE category=? ORDER BY last_seen DESC LIMIT 1""", (category,)).fetchall()
        return [{"summary": summary, "seen_count": count} for summary, count in rows]

    def remember_reference(self, reference: dict):
        if not reference.get("url", "").startswith("https://fisch.wiki/wiki/"):
            return
        term = reference["title"].casefold()
        with self._connect() as db:
            db.execute("""INSERT INTO wiki_references VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(term) DO UPDATE SET title=excluded.title,
                excerpt=excluded.excerpt, url=excluded.url,
                checked_at=excluded.checked_at""",
                (term, reference["title"], reference["excerpt"][:240],
                 reference["url"], reference["checked_at"]))

    def reference(self, term: str, max_age_seconds: int = 86400) -> dict | None:
        with self._connect() as db:
            row = db.execute("""SELECT title, excerpt, url, checked_at
                FROM wiki_references WHERE term=?""", (term.casefold(),)).fetchone()
        if not row or time.time() - row[3] > max_age_seconds:
            return None
        return dict(zip(("title", "excerpt", "url", "checked_at"), row))

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM scene_observations").fetchone()[0]

