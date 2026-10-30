"""Quoted conversations, never verified facts. JSONL is authoritative; FTS is disposable."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata

from .ownership import LogLease


EXPLICIT_RECALL = re.compile(r'前に.*(?:話|何|なに)|前の会話|この前|以前.*話|覚えて(?:る|いる|います)|思い出して|さっき.*話')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def grams(text):
    value = normalize(text)
    return {value[i:i+n] for n in (2, 3) for i in range(len(value)-n+1)}


def query_text(text):
    # Remove recall boilerplate, not substantive words. No model query rewriting.
    text = re.sub(r'前の会話|この前の会話|前に|以前|この前|さっき|覚えていますか|覚えている|覚えてる|思い出して|何を話した|何話した|なに話した|何の話|の話したよな|の話した|話したよな|話した|の話|したよな|教えて', ' ', text)
    return normalize(text.strip(' ？?。！!'))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


class SessionRecorder:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.records = []
        self._ids = {}
        self._lock = threading.RLock()
        self._poisoned = False
        raw = b''
        if self.path:
            with LogLease(str(self.path) + '.append'):
                raw = self.path.read_bytes() if self.path.exists() else b''
                for number, line in enumerate(raw.splitlines(keepends=True), 1):
                    try:
                        if not line.endswith(b'\n'):
                            raise ValueError('missing commit delimiter')
                        record = json.loads(line.decode('utf-8'), object_pairs_hook=_unique)
                        self.validate(record)
                        if record['turn_id'] in self._ids:
                            raise ValueError('duplicate turn_id')
                        self._ids[record['turn_id']] = record
                        self.records.append(record)
                    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                        raise ValueError(f'Session JSONL {self.path}, line {number}: invalid record; preserve and repair before restarting') from exc
        self._digest = hashlib.sha256(raw).digest()

    @staticmethod
    def validate(record):
        keys = {'session_id', 'turn_id', 'timestamp', 'status', 'user', 'assistant', 'provenance'}
        if not isinstance(record, dict) or set(record) != keys:
            raise ValueError('invalid session schema')
        if any(not isinstance(record[k], str) or not record[k] for k in ('session_id', 'turn_id')):
            raise ValueError('invalid session identity')
        if type(record['timestamp']) not in (int, float) or not math.isfinite(record['timestamp']):
            raise ValueError('invalid timestamp')
        if record['status'] != 'confirmed' or not all(isinstance(record[k], str) for k in ('user', 'assistant')):
            raise ValueError('only confirmed exchanges can enter Session JSONL')
        if not isinstance(record['provenance'], dict):
            raise ValueError('invalid provenance summary')
        json.dumps(record, ensure_ascii=False, allow_nan=False).encode('utf-8')

    def append(self, record):
        self.validate(record)
        with self._lock:
            if self._poisoned:
                raise OSError('session writer stopped after uncertain write; reopen')
            old = self._ids.get(record['turn_id'])
            if old is not None:
                if old == record:
                    return False
                raise ValueError('turn_id conflict')
            data = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
            if self.path:
                with LogLease(str(self.path) + '.append'):
                    raw = self.path.read_bytes() if self.path.exists() else b''
                    if hashlib.sha256(raw).digest() != self._digest:
                        raise OSError('Session JSONL changed by another writer; reopen')
                    try:
                        with self.path.open('ab') as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                    except OSError:
                        self._poisoned = True
                        raise
                    self._digest = hashlib.sha256(raw + data).digest()
            saved = copy.deepcopy(record)
            self._ids[saved['turn_id']] = saved
            self.records.append(saved)
            return True


class SessionIndex:
    def __init__(self, path=None):
        self.path = str(path) if path else ':memory:'
        self.records = []
        self._lock = threading.RLock()
        # Short-lived connections permit independent backup and Windows cleanup.
        self._memory = sqlite3.connect(':memory:', check_same_thread=False) if path is None else None
        with self.connection() as db:
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5(turn_id UNINDEXED, session_id UNINDEXED, user_terms, assistant_terms)')

    def connection(self):
        from contextlib import contextmanager
        @contextmanager
        def connect():
            db = self._memory or sqlite3.connect(self.path)
            try:
                with db:
                    yield db
            finally:
                if db is not self._memory:
                    db.close()
        return connect()

    def rebuild(self, records):
        for record in records:
            SessionRecorder.validate(record)
        with self._lock, self.connection() as db:
            db.execute('DELETE FROM turns')
            db.executemany('INSERT INTO turns VALUES(?,?,?,?)',
                [(r['turn_id'], r['session_id'], ' '.join(sorted(grams(r['user']))),
                  ' '.join(sorted(grams(r['assistant'])))) for r in records])
            self.records = copy.deepcopy(records)

    def add(self, record):
        SessionRecorder.validate(record)
        with self._lock, self.connection() as db:
            if db.execute('SELECT 1 FROM turns WHERE turn_id=?', (record['turn_id'],)).fetchone():
                return
            db.execute('INSERT INTO turns VALUES(?,?,?,?)', (record['turn_id'], record['session_id'],
                ' '.join(sorted(grams(record['user']))), ' '.join(sorted(grams(record['assistant'])))))
            self.records.append(copy.deepcopy(record))

    def search(self, text, *, explicit=False, now=None, max_sessions=None, hits_per_session=2, char_budget=None):
        now = time.time() if now is None else now
        max_sessions = (4 if explicit else 2) if max_sessions is None else max_sessions
        char_budget = (6000 if explicit else 2400) if char_budget is None else char_budget
        if max_sessions <= 0 or hits_per_session <= 0 or char_budget <= 0:
            return []
        query = query_text(text) if explicit else normalize(text)
        tokens = sorted(grams(query))[:96]
        with self._lock:
            records = {r['turn_id']: r for r in self.records}
            if tokens:
                match = ' OR '.join('"' + token + '"' for token in tokens)
                with self.connection() as db:
                    rows = db.execute('SELECT turn_id, bm25(turns,0,0,2,1) FROM turns WHERE turns MATCH ? ORDER BY 2 LIMIT 512', (match,)).fetchall()
                candidates = []
                for tid, bm25 in rows:
                    r = records.get(tid)
                    if r is None:
                        continue
                    qg = grams(query)
                    # Coverage and exact user match dominate assistant-only matches;
                    # BM25 resolves close lexical ties. Recency never invents relevance.
                    u = len(qg & grams(r['user'])) / len(qg)
                    a = len(qg & grams(r['assistant'])) / len(qg)
                    if max(u, a) < .20:
                        continue
                    score = 2*u + a + 2*int(query in normalize(r['user'])) + int(query in normalize(r['assistant']))
                    score += .05 / (1 + max(0, now-r['timestamp']) / 86400) + .01 * (-bm25)/(1+abs(bm25))
                    candidates.append((score, r))
            elif explicit and len(query) == 1:
                candidates = [(2*int(query in normalize(r['user'])) + int(query in normalize(r['assistant'])) + .05/(1+max(0, now-r['timestamp'])/86400), r)
                              for r in records.values() if query in normalize(r['user']+r['assistant'])]
            elif explicit and not query:
                candidates = [(r['timestamp'], r) for r in records.values()]
            else:
                return []
            # Stage 1: best evidence per session, not a sum biased to huge sessions.
            groups = {}
            for score, record in sorted(candidates, key=lambda x: (-x[0], -x[1]['timestamp'], x[1]['turn_id'])):
                groups.setdefault(record['session_id'], []).append((score, record))
            sessions = sorted(groups, key=lambda sid: (-groups[sid][0][0], sid))[:max_sessions]
            # Stage 2: windows within chosen sessions. Round-robin guarantees diversity.
            selected, seen, used = [], set(), 0
            for rank in range(hits_per_session):
                for sid in sessions:
                    hits = groups[sid]
                    if rank >= len(hits):
                        continue
                    score, r = hits[rank]
                    position = next(i for i, x in enumerate(self.records) if x['turn_id'] == r['turn_id'])
                    window = [x for x in self.records[max(0, position-1):position+2] if x['session_id'] == sid]
                    quoted = []
                    # Each chosen session gets a fair share even for huge turns.
                    window_used = 0
                    window_budget = char_budget // max(1, len(sessions)*hits_per_session)
                    # Anchor before neighbors so truncation cannot hide the actual hit.
                    for item in [r] + [x for x in window if x['turn_id'] != r['turn_id']]:
                        if item['turn_id'] in seen:
                            continue
                        remaining = min(char_budget-used, window_budget-window_used)
                        if remaining < 80:
                            continue
                        limit = min(700, remaining//2)
                        user_complete = len(item['user']) <= limit
                        assistant_complete = len(item['assistant']) <= limit
                        excerpt = {'turn_id': item['turn_id'], 'timestamp': item['timestamp'],
                                   'user': item['user'] if user_complete else '',
                                   'assistant': item['assistant'] if assistant_complete else '',
                                   'user_complete': user_complete, 'assistant_complete': assistant_complete,
                                   'user_source': 'user_statement', 'assistant_source': 'assistant_generated',
                                   'verified': False, 'sha256': hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
                        used += len(excerpt['user']) + len(excerpt['assistant'])
                        window_used += len(excerpt['user']) + len(excerpt['assistant'])
                        seen.add(item['turn_id'])
                        quoted.append(excerpt)
                    if quoted:
                        selected.append({'session_id': sid, 'hit_turn_id': r['turn_id'], 'score': round(score, 6), 'exchanges': quoted})
            return selected

    def close(self):
        if self._memory:
            self._memory.close()
