"""Opt-in, per-job conversation preferences. Raw is read only; never a grant.

Only complete labelled user declarations are accepted. No free-form extraction,
persona examples, assistant suggestions, executable policies or model training.
"""
import hashlib
import os
from pathlib import Path
import re
import sqlite3

from breaktail_memory_hub import source_rows


FIELDS = {
    '報告言語': ('report_language', {'日本語': 'Japanese', '英語': 'English'}),
    'コードコメント言語': ('code_comment_language', {'日本語': 'Japanese', '英語': 'English'}),
    '説明の長さ': ('explanation_length', {'短め': 'brief', '詳しく': 'detailed'}),
}
DECLARATION = re.compile(r'作業設定\s*[:：]\s*(報告言語|コードコメント言語|説明の長さ)\s*=\s*([^\s。]+)[。]?')


def validate_conversation_id(value):
    if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 128
                              or any(ord(c) < 32 for c in value)):
        raise ValueError('conversation id must be 1..128 characters without control characters')
    return value


def recall(config, conversation_id):
    """The caller explicitly binds this conversation to this job's workspace.

    Corrections use Raw append order, never model/timestamp guesses. Missing or
    unreadable evidence is reported as unavailable, not as an empty life history.
    """
    validate_conversation_id(conversation_id)
    report = {'conversation_id': conversation_id, 'scope': 'explicit_job_only',
              'preferences': {}, 'sources': [], 'execution_permission_granted': False}
    if conversation_id is None:
        return {**report, 'reason': 'not_requested'}
    if not config.get('data_root'):
        raise ValueError('conversation preference recall requires configured data_root')
    root = Path(config['data_root']).resolve()
    raw = Path(os.environ.get('BREAKTAIL_RAW_CONVERSATION_FILE',
                              root / 'raw/breaktail_raw_conversations.jsonl')).resolve()
    if not raw.is_relative_to(root):
        raise ValueError('Raw source points outside configured data_root')
    report['raw_file'] = str(raw)
    try:
        rows, scan = source_rows(raw, conversation_id, root / 'state/orchestrator.sqlite3')
        report.update(scan)
    except (OSError, ValueError, UnicodeError, sqlite3.Error) as error:
        return {**report, 'reason': 'source_unavailable', 'error': type(error).__name__}
    latest = {}
    for row in rows:
        if len(row['user_text']) > 160 or '\n' in row['user_text'] or '\r' in row['user_text']:
            continue
        match = DECLARATION.fullmatch(row['user_text'].strip())
        if not match:
            continue
        key, values = FIELDS[match[1]]
        value = match[2]
        if value != '解除' and value not in values:
            continue
        previous = latest.get(key)
        source = {'key': key, 'value': values.get(value), 'cleared': value == '解除',
                  'turn_id': row['turn_id'], 'timestamp': row['timestamp'],
                  'user_text': row['user_text'], 'source': 'explicit_user_declaration',
                  'user_text_sha256': hashlib.sha256(row['user_text'].encode('utf-8')).hexdigest()}
        if previous:
            source['supersedes_turn_id'] = previous['turn_id']
        latest[key] = source
    report['sources'] = list(latest.values())
    report['preferences'] = {key: source['value'] for key, source in latest.items() if not source['cleared']}
    return {**report, 'reason': 'source_verified' if latest else 'no_supported_declaration'}
