"""Bounded, workspace-local episodic recall from the agent's existing journals.

History is evidence to inspect, never instructions or proof about current files.
No model training and no writes to conversation/personality memory.
"""
from __future__ import annotations

import hashlib
import json
import re
from breaktail_agent_lessons import observed_recoveries


def _json(workspace, relative):
    path = workspace.path(relative, internal=True)
    if not path.is_file() or path.stat().st_size > 128000:
        raise ValueError('invalid journal size')
    return json.loads(path.read_text(encoding='utf-8'))


def _terms(text):
    text = text.casefold()
    words = set(re.findall(r'[a-z0-9_./-]{2,}', text))
    for part in re.findall(r'[ぁ-んァ-ヶ一-龥]{2,}', text):
        words.update(part[i:i+2] for i in range(len(part)-1))
    return words


def recall(workspace, task, *, limit=3):
    """Return relevant past episodes; absent/corrupt history never blocks work."""
    base = workspace.path('.breaktail-agent', internal=True)
    candidates = []
    for directory in base.iterdir():
        if not re.fullmatch(r'[0-9a-f]{32}', directory.name) or directory.name == workspace.run_id:
            continue
        try:
            path = workspace.path('.breaktail-agent/' + directory.name, internal=True)
            candidates.append((path.stat().st_mtime_ns, directory.name))
        except (OSError, ValueError):
            continue
    query = _terms(task)
    found = []
    for modified, identity in sorted(candidates, reverse=True)[:100]:
        prefix = '.breaktail-agent/' + identity
        try:
            previous = _json(workspace, prefix + '/task.json')
            result = _json(workspace, prefix + '/result.json')
            if result['run_id'] != identity or result['workspace'] != str(workspace.root):
                continue
            if not isinstance(previous['task'], str) or result['status'] not in ('completed', 'step_limit', 'model_failed', 'cancelled', 'time_limit','stalled'):
                continue
            changes = result['changes']
            if not isinstance(changes, list) or len(changes) > 200:
                continue
            files = []
            for change in changes:
                name, expected = change['path'], change['after_sha256']
                path = workspace.path(name)
                if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                    raise ValueError('invalid digest')
                same = path.is_file() and path.stat().st_size <= 64000 and hashlib.sha256(path.read_bytes()).hexdigest() == expected
                files.append({'path': name, 'matches_previous_result': same})
            score = len(query & _terms(previous['task'] + ' ' + ' '.join(f['path'] for f in files)))
            if score == 0:
                continue
            failures = []
            events = []
            event_path = workspace.path(prefix + '/events.jsonl', internal=True)
            if event_path.is_file() and event_path.stat().st_size <= 2000000:
                for line in event_path.read_text(encoding='utf-8').splitlines():
                    event = json.loads(line)
                    events.append(event)
                    if event.get('error'):
                        # Deliberately exclude arbitrary exception text/code from lessons.
                        failures.append({'step': event['step'], 'error': str(event['error'])[:60]})
                    elif isinstance(event.get('result'), dict) and event['result'].get('ok') is False:
                        failures.append({'step': event['step'], 'tool': str(event.get('tool', ''))[:40], 'ok': False})
            episode = {'source': prefix + '/result.json', 'run_id': identity,
                'previous_task': previous['task'][:600], 'previous_status': result['status'],
                'previous_checks': {'syntax_verified': result.get('syntax_verified') is True,
                    'tests_passed': result.get('tests_passed') is True},
                'files': files[:12], 'previous_failures': failures[-6:],
                'observed_recoveries': observed_recoveries(workspace,events,result),
                'current_checks_required': True}
            found.append((score, modified, episode))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    selected = []
    for _, _, episode in sorted(found, key=lambda x: (x[0], x[1]), reverse=True):
        if len(json.dumps(selected + [episode], ensure_ascii=False)) > 4000:
            continue
        selected.append(episode)
        if len(selected) >= min(max(limit, 1), 3):
            break
    return selected
