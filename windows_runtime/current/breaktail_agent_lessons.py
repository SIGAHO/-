"""Derive bounded observed recovery sequences; never infer a failure's cause.

Historical success is not proof for a new task. Evidence is limited to the
recorded Python inputs and does not certify dependencies or test completeness.
"""
from pathlib import Path
import re


def _manifest(workspace,event):
    evidence=event.get('verification')
    if not isinstance(evidence,dict) or evidence.get('schema')!=1 or evidence.get('stable_during_check') is not True:
        return None
    files=evidence.get('files')
    if not isinstance(files,dict) or not 1<=len(files)<=200:return None
    for name,digest in files.items():
        workspace.path(name)
        if not name.endswith('.py') or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):return None
    return files


def _tests(files):
    return {name:digest for name,digest in files.items() if Path(name).name.startswith('test_')}


def observed_recoveries(workspace,events,result):
    """Match same-kind fail -> actual file edits -> pass, with final readback.

    Old records without input manifests decline. Changing/removing a discovered
    test suppresses a unit-test recovery rather than certifying a repair.
    """
    if result.get('status')!='completed' or not isinstance(events,list) or len(events)>40:return []
    if any(not isinstance(e,dict) or type(e.get('step')) is not int for e in events):return []
    steps=[e['step'] for e in events]
    if steps!=sorted(set(steps)):return []
    recovered=[]
    pending={}
    writes=[]
    for event in events:
        tool=event.get('tool')
        value=event.get('result')
        if tool in ('write_file','replace_text') and isinstance(value,dict) and value.get('written') is True:
            writes.append((event['step'],value))
        if tool not in ('check_python','run_tests'):continue
        manifest=_manifest(workspace,event)
        if manifest is None:
            pending.pop(tool,None)
            continue
        nonempty_test=(isinstance(value,dict) and isinstance(value.get('output'),str)
                       and bool(re.search(r'^TEST_COUNT=[1-9][0-9]*\r?$',value['output'],re.M)))
        failed=(event.get('error') in ('SyntaxError','IndentationError','TabError') if tool=='check_python' else
                nonempty_test and value.get('ok') is False and value.get('timeout') is False
                and type(value.get('exit_code')) is int and value['exit_code']!=0)
        passed=isinstance(value,dict) and value.get('ok') is True
        if tool=='run_tests':passed=passed and nonempty_test and value.get('exit_code')==0 and value.get('timeout') is False
        if failed:
            pending[tool]=(event,manifest)
            continue
        if not passed or tool not in pending:continue
        failure,before=pending.pop(tool)
        if not result.get('syntax_verified' if tool=='check_python' else 'tests_passed'):continue
        if tool=='run_tests' and (not _tests(before) or _tests(before)!=_tests(manifest)):continue
        edits={}
        for step,write in writes:
            name=write.get('path')
            if (step>failure['step'] and name in before and name in manifest
                    and before[name]!=manifest[name] and write.get('sha256')==manifest[name]):
                edits[name]=step
        if not edits or len(edits)>6:continue
        final={c['path']:c.get('after_sha256') for c in result.get('changes',[]) if isinstance(c,dict) and 'path' in c}
        if any(final.get(name)!=manifest[name] for name in edits):continue
        try:
            current_match=workspace.verification_snapshot()==manifest
        except (OSError,ValueError):
            current_match=False
        recovered.append({'kind':'observed_recheck_after_edit','check_tool':tool,
            'failure_step':failure['step'],'edit_steps':sorted(set(edits.values())),
            'passed_step':event['step'],'edited_paths':sorted(edits),
            'test_files_unchanged':True if tool=='run_tests' else None,
            'current_python_inputs_match':current_match,'cause_inferred':False,
            'evidence_file':'events.jsonl','current_checks_required':True})
    return recovered[-2:]
