"""Versioned, review-gated preference outbox. Never trains or labels itself.

Candidates and append-only human reviews stay separate. A candidate's claimed
human_approved flag is insufficient: promotion requires a matching review.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import threading
from .ownership import LogLease


SOURCES = ('real_user_feedback', 'human_authored_approved', 'external_teacher_candidate')


def group_split(session_id):
    bucket = int(hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:8], 16) % 100
    return 'blind_holdout' if bucket < 10 else 'dev' if bucket < 25 else 'train'


def validate(record, target_model='qwen2.5:14b'):
    required = {'schema_version', 'id', 'context', 'raw_turn_ids', 'response_spec', 'chosen', 'rejected',
                'source_type', 'teacher_model', 'teacher_generated', 'human_approved', 'provenance',
                'session_id', 'turn_id', 'split'}
    if not isinstance(record, dict) or not required <= record.keys() or record['schema_version'] != 1:
        raise ValueError('invalid preference schema')
    if record['source_type'] not in SOURCES:
        raise ValueError('unknown preference source')
    if any(not isinstance(record[k], str) or not record[k] for k in ('id', 'session_id', 'turn_id')):
        raise ValueError('missing preference identity')
    if not isinstance(record['context'], list) or not isinstance(record['raw_turn_ids'], list) or not isinstance(record['response_spec'], dict) or not isinstance(record['provenance'], dict):
        raise ValueError('invalid preference context')
    if any(type(record[k]) is not bool for k in ('teacher_generated', 'human_approved')):
        raise ValueError('approval flags must be boolean')
    if record['split'] != group_split(record['session_id']):
        raise ValueError('session split mismatch')
    if not any(record[k] for k in ('chosen', 'rejected')) or any(record[k] is not None and (not isinstance(record[k], str) or not record[k].strip()) for k in ('chosen', 'rejected')):
        raise ValueError('missing preference text')
    if record['source_type'] == 'external_teacher_candidate':
        teacher = record['teacher_model']
        if not record['teacher_generated'] or not isinstance(teacher, str) or not teacher.strip():
            raise ValueError('teacher provenance missing')
        # Model family aliases are intentionally conservative. An inference
        # target cannot masquerade as an independent teacher via a tag change.
        if (target_model.casefold().split(':')[0] in teacher.casefold()
                or re.search(r'qwen[ /_-]*2\.?5', teacher, re.IGNORECASE)):
            raise ValueError('target model cannot supply teacher correctness')
        if record['human_approved']:
            raise ValueError('teacher candidates require separate human review')
    elif record['teacher_generated'] or record['teacher_model'] is not None:
        raise ValueError('inconsistent teacher provenance')


class PreferenceStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.records = {}
        self.reviews = {}
        self._digests = {}
        self._poisoned = False
        for name, target in [('candidates.jsonl', self.records), ('reviews.jsonl', self.reviews)]:
            file = self.path / name if self.path else None
            self._digests[name] = hashlib.sha256(b'').digest()
            if file and file.exists():
                raw = file.read_bytes()
                self._digests[name] = hashlib.sha256(raw).digest()
                if raw and not raw.endswith(b'\n'):
                    raise ValueError('incomplete preference ledger; preserve and repair')
                for line in raw.decode('utf-8').splitlines():
                    row = json.loads(line)
                    if name == 'candidates.jsonl':
                        validate(row)
                    else:
                        self.validate_review(row)
                    if row['id'] in target:
                        raise ValueError('duplicate preference ledger identity')
                    target[row['id']] = row

    def write(self, name, record):
        if self.path:
            self.path.mkdir(parents=True, exist_ok=True)
            file = self.path / name
            data = (json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n').encode('utf-8')
            with LogLease(str(file) + '.append'):
                raw = file.read_bytes() if file.exists() else b''
                if self._poisoned or hashlib.sha256(raw).digest() != self._digests[name]:
                    raise OSError('preference ledger changed or uncertain write; reopen')
                try:
                    with file.open('ab') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                except OSError:
                    self._poisoned = True
                    raise
                self._digests[name] = hashlib.sha256(raw + data).digest()

    def append(self, record):
        validate(record)
        with self.lock:
            previous = self.records.get(record['id'])
            if previous is not None:
                if previous != record:
                    raise ValueError('preference ID conflict')
                return False
            self.write('candidates.jsonl', record)
            self.records[record['id']] = record
            return True

    @staticmethod
    def digest(record):
        return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def validate_review(review):
        if (not isinstance(review, dict) or set(review) != {'id', 'candidate_sha256', 'reviewer', 'approved'}
                or not isinstance(review['id'], str) or not isinstance(review['reviewer'], str)
                or not review['reviewer'].strip() or type(review['approved']) is not bool
                or not isinstance(review['candidate_sha256'], str) or len(review['candidate_sha256']) != 64):
            raise ValueError('invalid human review')

    def approve(self, id, *, reviewer):
        """Explicit operator action only; never called from runtime feedback."""
        record = self.records[id]
        review = {'id': id, 'candidate_sha256': self.digest(record), 'reviewer': reviewer, 'approved': True}
        self.validate_review(review)
        with self.lock:
            if id in self.reviews:
                if self.reviews[id] != review:
                    raise ValueError('review already exists')
                return
            self.write('reviews.jsonl', review)
            self.reviews[id] = review

    def trusted(self, split='train'):
        if split not in {'train', 'dev'}:
            raise ValueError('blind holdout cannot be exported for training/tuning')
        rows = []
        for row in self.records.values():
            review = self.reviews.get(row['id'], {})
            if (row['split'] == split and review.get('approved') is True
                    and review.get('candidate_sha256') == self.digest(row)):
                rows.append({**row, 'human_approved': True})
        # Strongest source wins only for the same original context and response.
        selected = {}
        for row in sorted(rows, key=lambda r: (SOURCES.index(r['source_type']), r['id'])):
            key = (row['session_id'], tuple(row['raw_turn_ids']), row['chosen'], row['rejected'])
            selected.setdefault(key, row)
        return list(selected.values())

    def counts(self):
        return {'candidates': len(self.records), 'human_approved': sum(
            r.get('approved') is True and r.get('candidate_sha256') == self.digest(self.records[id])
            for id, r in self.reviews.items() if id in self.records),
            'teacher_generated': sum(r['teacher_generated'] for r in self.records.values())}
