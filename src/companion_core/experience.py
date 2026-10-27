"""Independent experience ledger. Heat measures salience, never truth/confidence."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
import time

from .session_memory import grams


@dataclass(frozen=True)
class HeatConfig:
    half_life_seconds: float = 7 * 86400
    reinforcement: float = .25
    maximum: float = 4.0

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in (self.half_life_seconds, self.reinforcement, self.maximum)):
            raise ValueError('heat parameters must be positive finite numbers')


class ExperienceStore:
    KINDS = {'turn', 'correction', 'task_completion', 'retrieval_success', 'retrieval_failure', 'model_failure',
             'assistant_response', 'next_user_reaction', 'decision', 'tool', 'drop'}

    def __init__(self, path=None, *, config=None):
        self.path = str(path) if path else None
        self.config = config or HeatConfig()
        self._memory = sqlite3.connect(':memory:', check_same_thread=False) if path is None else None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY, kind TEXT NOT NULL, turn_id TEXT NOT NULL, timestamp REAL NOT NULL, source TEXT NOT NULL, body TEXT NOT NULL, heat REAL NOT NULL, heated_at REAL NOT NULL, references_count INTEGER NOT NULL DEFAULT 0)')

    def connection(self):
        from contextlib import contextmanager
        @contextmanager
        def connect():
            db = self._memory or sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                if db is not self._memory:
                    db.close()
        return connect()

    def append(self, *, id, kind, turn_id, timestamp, source, body, heat=None):
        if kind not in self.KINDS or source not in {'user_statement', 'user_correction', 'assistant_generated', 'runtime'}:
            raise ValueError('invalid experience type/source')
        if not isinstance(id, str) or not id or not isinstance(turn_id, str) or not turn_id:
            raise ValueError('invalid experience identity')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not isinstance(body, dict):
            raise ValueError('invalid experience event')
        value = .5 if kind == 'turn' else 1.0
        value = value if heat is None else heat
        if not math.isfinite(value) or not 0 <= value <= self.config.maximum:
            raise ValueError('invalid initial heat')
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False, sort_keys=True)
        with self.connection() as db:
            old = db.execute('SELECT * FROM experiences WHERE id=?', (id,)).fetchone()
            if old:
                if (old['kind'], old['turn_id'], old['timestamp'], old['source'], old['body']) != (kind, turn_id, timestamp, source, raw):
                    raise ValueError('experience ID conflict')
                return False
            db.execute('INSERT INTO experiences VALUES(?,?,?,?,?,?,?,?,0)', (id, kind, turn_id, timestamp, source, raw, value, timestamp))
            return True

    def live_heat(self, row, now):
        return row['heat'] * 2 ** (-max(0, now-row['heated_at']) / self.config.half_life_seconds)

    def reinforce(self, ids, *, now=None):
        now = time.time() if now is None else now
        if not math.isfinite(now):
            raise ValueError('invalid time')
        with self.connection() as db:
            for id in dict.fromkeys(ids):
                row = db.execute('SELECT * FROM experiences WHERE id=?', (id,)).fetchone()
                if row:
                    effective = max(now, row['heated_at'])
                    heat = min(self.config.maximum, self.live_heat(row, effective) + self.config.reinforcement)
                    db.execute('UPDATE experiences SET heat=?, heated_at=?, references_count=references_count+1 WHERE id=?', (heat, effective, id))

    def all(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM experiences ORDER BY timestamp, id')]

    def salient(self, text, *, now=None, limit=2, reinforce=False, kinds=None):
        now = time.time() if now is None else now
        qg = grams(text)
        if not qg or limit <= 0:
            return []
        # Bounded recent candidate window; common turn events are not lessons.
        with self.connection() as db:
            rows = db.execute("SELECT * FROM experiences WHERE kind!='turn' ORDER BY timestamp DESC, id LIMIT 512").fetchall()
        scored = []
        for row in rows:
            if kinds is not None and row['kind'] not in kinds:
                continue
            body = json.loads(row['body'])
            # Only original user text or structured error target can match. Never AI prose.
            target = str(body.get('user', '')) + ' ' + str(body.get('target', ''))
            coverage = len(qg & grams(target)) / len(qg)
            heat = self.live_heat(row, now)
            if coverage >= .25 and heat >= .01:
                scored.append((coverage * heat, row, body, heat))
        selected = sorted(scored, key=lambda x: (-x[0], -x[1]['timestamp'], x[1]['id']))[:limit]
        result = [{'id': r['id'], 'kind': r['kind'], 'turn_id': r['turn_id'], 'timestamp': r['timestamp'],
                   'source': r['source'], 'body': {k: (v[:600] if isinstance(v, str) else v) for k, v in b.items()},
                   'live_heat': round(h, 6), 'verified': False, 'fact_evidence': False}
                  for _, r, b, h in selected]
        if reinforce:
            self.reinforce([r['id'] for r in result], now=now)
        return result

    def close(self):
        if self._memory:
            self._memory.close()
