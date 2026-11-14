"""Experimental, read-only repair examples. Not wired into default recall.

Only short changes with owned backups, matching current source and unchanged
test evidence qualify. A run-start backup is not the failed-check snapshot.
"""
import copy
import difflib
import hashlib
import json
from pathlib import Path
import re

from breaktail_agent_lessons import observed_recoveries


def _json(workspace,name):
    path=workspace.path(name,internal=True)
    if not path.is_file() or path.stat().st_size>128000:raise ValueError('invalid journal')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('journal must be an object')
    return value


def _bytes(path):
    if not path.is_file() or path.stat().st_size>64000:raise ValueError('example exceeds limit')
    return path.read_bytes()


def _digest(value):return hashlib.sha256(value).hexdigest()


def _examples(workspace,episode):
    identity=episode.get('run_id')
    if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):return []
    prefix='.breaktail-agent/'+identity
    if episode.get('source')!=prefix+'/result.json':return []
    task=_json(workspace,prefix+'/task.json')
    result=_json(workspace,prefix+'/result.json')
    if (task.get('workspace')!=str(workspace.root) or result.get('workspace')!=str(workspace.root)
            or result.get('run_id')!=identity or result.get('status')!='completed'
            or result.get('syntax_verified') is not True or result.get('tests_passed') is not True
            or result.get('execution_enabled') is not True):return []
    event_path=workspace.path(prefix+'/events.jsonl',internal=True)
    if not event_path.is_file() or event_path.stat().st_size>2000000:return []
    events=[json.loads(line) for line in event_path.read_text(encoding='utf-8').splitlines()]
    recoveries=observed_recoveries(workspace,events,result)
    examples=[]
    for recovery in recoveries:
        if recovery['check_tool']!='run_tests' or recovery['test_files_unchanged'] is not True:continue
        passed=next(e for e in events if e['step']==recovery['passed_step'])
        manifest=passed['verification']['files']
        # Added current tasks are allowed; historical test inputs must still match.
        if any(_digest(_bytes(workspace.path(name)))!=digest for name,digest in manifest.items()
               if Path(name).name.startswith('test_')):continue
        for name in recovery['edited_paths']:
            path=workspace.path(name)
            if path.suffix!='.py' or any(p.lower() in ('test','tests') for p in path.relative_to(workspace.root).parts):continue
            if path.name.startswith('test_') or path.name.endswith('_test.py') or path.name=='conftest.py':continue
            change=next(c for c in result['changes'] if c['path']==name)
            backup_name=change.get('backup')
            if not isinstance(backup_name,str):continue
            backup=workspace.path(backup_name,internal=True)
            if backup.parent!=workspace.path(prefix,internal=True) or not re.fullmatch(r'before-[0-9]+',backup.name):continue
            before,after=_bytes(backup),_bytes(path)
            if _digest(before)!=change.get('before_sha256') or _digest(after)!=change.get('after_sha256'):continue
            if _digest(after)!=manifest.get(name):continue
            lines=list(difflib.unified_diff(before.decode('utf-8-sig').splitlines(),after.decode('utf-8-sig').splitlines(),
                fromfile=name+'@run_start',tofile=name+'@verified_result',n=1,lineterm=''))
            patch='\n'.join(lines)
            if not patch or len(lines)>16 or len(patch)>1000:continue
            examples.append({'kind':'historical_verified_run_change','source':prefix+'/result.json',
                'backup_source':backup_name,'path':name,'before_sha256':change['before_sha256'],
                'after_sha256':change['after_sha256'],'before_scope':'run_start_not_failure_snapshot',
                'failure_step':recovery['failure_step'],'passed_step':recovery['passed_step'],
                'verification':'run_tests','patch':patch,'cause_inferred':False,
                'instruction_authority':'none','current_checks_required':True})
            return examples  # At most one small example per episode.
    return examples


def augment(workspace,episodes):
    """Return a candidate context without modifying journals or input episodes."""
    result=copy.deepcopy(episodes)
    for episode in result:
        try:
            examples=_examples(workspace,episode)
            if not examples:continue
            episode['verified_change_examples']=examples
            if len(json.dumps(result,ensure_ascii=False))>4000:
                episode.pop('verified_change_examples')
        except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration):
            continue
    return result
