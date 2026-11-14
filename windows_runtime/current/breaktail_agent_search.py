"""Bounded literal UTF-8 search through the existing workspace path guard."""
import hashlib
import os
from collections import Counter
from pathlib import Path

MAX_ENTRIES = 2000
MAX_FILES = 200
MAX_BYTES = 2_000_000
MAX_MATCHES = 40
MAX_FILE_BYTES = 64000
EXCLUDED_DIRS = {'node_modules', '__pycache__', 'venv', 'env'}
EXCLUDED_SUFFIXES = {'.exe', '.dll', '.sys', '.key', '.pfx', '.pem', '.sqlite', '.db'}


def search(workspace, query, name='.'):
    if not isinstance(query, str) or not query or len(query) > 200 or any(c in query for c in '\r\n\x00'):
        raise ValueError('query must be a single-line literal of 1..200 characters')
    start = workspace.path(name)
    relative = start.relative_to(workspace.root)
    if any(p.startswith('.') or p.lower() in EXCLUDED_DIRS for p in relative.parts):
        raise ValueError('hidden/excluded search scope')
    if not start.exists():
        raise ValueError('search scope does not exist')
    skipped = Counter()
    matches = []
    entries = files = bytes_read = 0
    limited = []
    pending = [start]
    while pending and not limited:
        candidate = pending.pop()
        try:
            path = workspace.path(str(candidate.relative_to(workspace.root)))
            if path.is_dir():
                with os.scandir(path) as directory:
                    for entry in directory:
                        if entries >= MAX_ENTRIES:
                            limited.append('entries')
                            break
                        entries += 1
                        if entry.name.startswith('.'):
                            skipped['hidden'] += 1
                        elif entry.is_symlink() or Path(entry.path).is_junction():
                            skipped['links'] += 1
                        elif entry.is_dir(follow_symlinks=False) and entry.name.lower() in EXCLUDED_DIRS:
                            skipped['excluded_directory'] += 1
                        else:
                            pending.append(Path(entry.path))
                continue
            if not path.is_file():
                skipped['non_file'] += 1
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                skipped['excluded_suffix'] += 1
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped['oversized'] += 1
                continue
            if files >= MAX_FILES or bytes_read + MAX_FILE_BYTES + 1 > MAX_BYTES:
                limited.append('files' if files >= MAX_FILES else 'bytes')
                break
            with path.open('rb') as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
            files += 1
            bytes_read += len(data)
            if len(data) > MAX_FILE_BYTES:
                skipped['oversized'] += 1
                continue
            if b'\x00' in data:
                skipped['binary'] += 1
                continue
            try:
                content = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                skipped['non_utf8'] += 1
                continue
            sha = hashlib.sha256(data).hexdigest()
            for number, line in enumerate(content.splitlines(), 1):
                offset = line.find(query)
                if offset < 0:
                    continue
                left = max(0, offset - 60)
                quote = line[left:left + 320]
                matches.append({'path':str(path.relative_to(workspace.root)), 'line':number,
                                'column':offset + 1, 'quote':quote, 'quote_start_column':left + 1,
                                'quote_truncated':left > 0 or left + len(quote) < len(line), 'sha256':sha})
                if len(matches) >= MAX_MATCHES:
                    limited.append('matches')
                    break
        except (OSError, ValueError):
            skipped['inaccessible_or_protected'] += 1
    return {'query':query, 'path':str(relative) or '.', 'mode':'case_sensitive_literal',
            'matches':matches, 'entries_seen':entries, 'files_read':files, 'bytes_read':bytes_read,
            'skipped':dict(skipped), 'scan_limited':bool(limited), 'limit_reasons':limited,
            'coverage':'eligible UTF-8 files only; exclusions and budgets apply',
            'limits':{'entries':MAX_ENTRIES,'files':MAX_FILES,'bytes':MAX_BYTES,
                      'file_bytes':MAX_FILE_BYTES,'matches':MAX_MATCHES},
            'requires_read_before_edit':True}
