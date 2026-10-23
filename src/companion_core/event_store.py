from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from .models import Event, SourceType
from .ownership import LogLease


class EventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[Event] = []
        self._ids = {}
        self._digest = hashlib.sha256(b'').digest()
        self._lock = threading.RLock()
        self._poisoned = False
        if self.path:
            with LogLease(str(self.path) + '.append'):
                if self.path.exists():
                    self._load()

    @staticmethod
    def validate(d):
        if not isinstance(d, dict) or set(d) != {'id', 'kind', 'payload', 'source', 'ts'}:
            raise ValueError('invalid event schema')
        if not isinstance(d['id'], str) or not d['id'] or not isinstance(d['kind'], str) or not d['kind']:
            raise ValueError('invalid event identity')
        if not isinstance(d['payload'], dict) or type(d['ts']) not in (int, float) or not math.isfinite(d['ts']):
            raise ValueError('invalid payload or timestamp')
        if d['kind'] not in {'user_input', 'assistant_output', 'correction', 'runtime_observation'}:
            raise ValueError('unknown event kind')
        SourceType(d['source'])
        if d['kind'] in {'user_input', 'assistant_output'} and not isinstance(d['payload'].get('text'), str):
            raise ValueError('missing text')
        if d['kind'] == 'correction' and (not isinstance(d['payload'].get('key'), str) or 'new' not in d['payload']):
            raise ValueError('invalid correction')
        json.dumps(d, ensure_ascii=False, allow_nan=False).encode('utf-8')

    def _load(self):
        raw = self.path.read_bytes()
        for number, line in enumerate(raw.splitlines(keepends=True), 1):
            try:
                if not line.endswith(b'\n') or not line.strip():
                    raise ValueError('missing commit delimiter or empty record')
                def unique_object(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError('duplicate JSON key')
                        result[key] = value
                    return result
                d = json.loads(line.decode('utf-8'), object_pairs_hook=unique_object)
                self.validate(d)
                if d['id'] in self._ids:
                    raise ValueError('duplicate event ID')
                event = Event(id=d['id'], kind=d['kind'], payload=d['payload'], source=SourceType(d['source']), ts=d['ts'])
                self.events.append(event)
                self._ids[event.id] = copy.deepcopy(d)
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError(f'Event log {self.path}, line {number}: invalid record; preserve and repair before restarting') from exc
        self._digest = hashlib.sha256(raw).digest()

    def append(self, event: Event):
        with self._lock:
            if self._poisoned:
                raise OSError('writer stopped after an uncertain disk write; reopen and replay')
            d = event.to_dict()
            self.validate(d)
            data = (json.dumps(d, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with LogLease(str(self.path) + '.append'):
                    raw = self.path.read_bytes() if self.path.exists() else b''
                    if hashlib.sha256(raw).digest() != self._digest:
                        raise OSError('ログが別の書き込み元により変更されました。daemon経由で再接続してください')
                    if d['id'] in self._ids:
                        if self._ids[d['id']] == d:
                            return False
                        raise ValueError('event ID conflict')
                    try:
                        with self.path.open('ab') as f:
                            f.write(data)
                            f.flush()
                            os.fsync(f.fileno())
                    except OSError:
                        self._poisoned = True
                        raise
                    self._digest = hashlib.sha256(raw + data).digest()
            elif d['id'] in self._ids:
                if self._ids[d['id']] == d:
                    return False
                raise ValueError('event ID conflict')
            self.events.append(copy.deepcopy(event))
            self._ids[d['id']] = copy.deepcopy(d)
            return True
