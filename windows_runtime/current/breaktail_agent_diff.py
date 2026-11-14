"""Read-only, bounded review of this run's tracked file changes."""
import difflib
import hashlib
from pathlib import Path
import re

MAX_FILES = 20
MAX_FILE_BYTES = 64000
MAX_LINES = 2000
MAX_PATCH_CHARS = 12000
MAX_FILE_PATCH_CHARS = 4000


def _read(path):
    with path.open('rb') as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('file_size_limit')
    return data


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def review(workspace):
    rows = []
    patch_budget = MAX_PATCH_CHARS
    changes = list(workspace.changes.values())
    for change in changes[:MAX_FILES]:
        row = {'path':change['path'], 'before_sha256':change['before_sha256'],
               'expected_after_sha256':change['after_sha256'], 'diff':None,
               'diff_truncated':False}
        rows.append(row)
        try:
            current = workspace.path(change['path'])
            if not current.exists():
                row['status'] = 'missing'
                continue
            after = _read(current)
            row['current_sha256'] = _sha(after)
            if row['current_sha256'] != change['after_sha256']:
                row['status'] = 'external_change'
                continue
            before = b''
            if change['before_sha256'] is not None:
                backup_name = change.get('backup')
                parts = Path(backup_name).parts if isinstance(backup_name, str) else ()
                if (len(parts) != 3 or parts[0] != '.breaktail-agent'
                        or not re.fullmatch(r'[0-9a-f]{32}', parts[1])
                        or not re.fullmatch(r'before-[0-9]+', parts[2])):
                    row['status'] = 'backup_invalid'
                    continue
                before = _read(workspace.path(backup_name, internal=True))
                if _sha(before) != change['before_sha256']:
                    row['status'] = 'backup_invalid'
                    continue
            elif change.get('backup') is not None:
                row['status'] = 'backup_invalid'
                continue
            row['integrity'] = 'verified'
            row['status'] = ('added' if change['before_sha256'] is None else
                             'unchanged' if before == after else 'modified')
            if b'\x00' in before or b'\x00' in after:
                row['diff_unavailable'] = 'binary'
                continue
            try:
                old = before.decode('utf-8-sig')
                new = after.decode('utf-8-sig')
            except UnicodeDecodeError:
                row['diff_unavailable'] = 'non_utf8'
                continue
            old_lines, new_lines = old.splitlines(), new.splitlines()
            row['text_format'] = {
                'line_endings_normalized_in_diff':True,
                'before_ends_with_newline':old.endswith(('\r', '\n')),
                'after_ends_with_newline':new.endswith(('\r', '\n')),
                'before_utf8_bom':before.startswith(b'\xef\xbb\xbf'),
                'after_utf8_bom':after.startswith(b'\xef\xbb\xbf')}
            if max(len(old_lines), len(new_lines)) > MAX_LINES:
                row['diff_unavailable'] = 'line_count_limit'
                continue
            budget = min(MAX_FILE_PATCH_CHARS, patch_budget)
            fragments = []
            for line in difflib.unified_diff(old_lines, new_lines,
                    fromfile='before/'+change['path'], tofile='current/'+change['path'], lineterm=''):
                fragment = line+'\n'
                if len(fragment) > budget:
                    fragments.append(fragment[:budget])
                    row['diff_truncated'] = True
                    break
                fragments.append(fragment)
                budget -= len(fragment)
            row['diff'] = ''.join(fragments)
            patch_budget -= len(row['diff'])
        except (OSError, ValueError) as error:
            row['status'] = 'unavailable'
            row['error'] = type(error).__name__
    return {'scope':'current_run_tracked_changes', 'read_only':True, 'changes':rows,
            'total_tracked':len(changes), 'files_omitted':max(0,len(changes)-MAX_FILES),
            'output_limited':len(changes)>MAX_FILES or any(
                r['diff_truncated'] or r.get('diff_unavailable')=='line_count_limit' for r in rows),
            'limits':{'files':MAX_FILES, 'file_bytes':MAX_FILE_BYTES, 'lines_per_file':MAX_LINES,
                      'patch_characters':MAX_PATCH_CHARS, 'patch_characters_per_file':MAX_FILE_PATCH_CHARS},
            'verification_granted':False}
