"""Resume only a settled, validated run; never replay old tool calls."""
import json
import re


def _load(workspace,relative):
    path=workspace.path(relative,internal=True)
    if not path.is_file() or path.stat().st_size>256000:raise ValueError('invalid resume record')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('resume record must be an object')
    return value


def load(workspace,identity,model):
    if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):
        raise ValueError('resume run id must be 32 lowercase hexadecimal characters')
    prefix='.breaktail-agent/'+identity
    if workspace.path(prefix+'/resume_claim.json',internal=True).exists():
        claim=_load(workspace,prefix+'/resume_claim.json')
        raise ValueError('run already continued as '+str(claim.get('child_run_id')))
    task=_load(workspace,prefix+'/task.json')
    result=_load(workspace,prefix+'/result.json')
    if task.get('checkpoint_schema')!=1:raise ValueError('older run is not a resumable checkpoint')
    if result.get('run_id')!=identity or result.get('workspace')!=str(workspace.root) or task.get('workspace')!=str(workspace.root):
        raise ValueError('resume checkpoint belongs to a different workspace')
    if result.get('status') not in ('step_limit','model_failed','cancelled','time_limit','stalled'):raise ValueError('only an incomplete settled run can resume')
    if task.get('model')!=model:raise ValueError('resume model differs from checkpoint')
    requirements=None
    requirements_path=workspace.path(prefix+'/requirements.json',internal=True)
    if task.get('requirements_sha256') is not None:
        requirements=_load(workspace,prefix+'/requirements.json')
        if requirements_digest(requirements)!=task['requirements_sha256']:raise ValueError('resume requirements changed')
    elif requirements_path.exists():raise ValueError('unexpected resume requirements')
    changes=result.get('changes')
    if not isinstance(changes,list) or len(changes)>200:raise ValueError('invalid resume changes')
    validated=[]
    seen=set()
    for change in changes:
        if not isinstance(change,dict):raise ValueError('invalid resume change')
        name=change.get('path')
        path=workspace.path(name)
        expected=change.get('after_sha256')
        if str(path) in seen or not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):raise ValueError('invalid checkpoint digest')
        seen.add(str(path))
        if not path.is_file() or path.stat().st_size>64000 or _digest(path.read_bytes())!=expected:
            raise ValueError('file changed since checkpoint: '+name)
        before=change.get('before_sha256')
        backup=change.get('backup')
        original=None
        if before is not None:
            if not isinstance(before,str) or not re.fullmatch(r'[0-9a-f]{64}',before):raise ValueError('invalid backup digest')
            if not isinstance(backup,str):raise ValueError('missing backup')
            expected_parent=workspace.path(prefix,internal=True)
            backup_path=workspace.path(backup,internal=True)
            if backup_path.parent!=expected_parent or not re.fullmatch(r'before-[0-9]+',backup_path.name):raise ValueError('backup is not owned by checkpoint')
            if not backup_path.is_file() or backup_path.stat().st_size>64000:raise ValueError('invalid backup')
            original=backup_path.read_bytes()
            if _digest(original)!=before:raise ValueError('backup changed since checkpoint')
        elif backup is not None:raise ValueError('unexpected backup for new file')
        validated.append((str(path),dict(change),original))
    revision=result.get('revision')
    if type(revision) is not int or revision<0:raise ValueError('invalid checkpoint revision')
    return {'task':task.get('task'),'requirements':requirements,'changes':validated,
            'revision':revision,'plan':result.get('plan'),'source':identity,
            'conversation_id':task.get('conversation_id')}


def _digest(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def requirements_digest(value):
    return _digest(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')) if value is not None else None


def restore(workspace,state):
    for index,(path,change,original) in enumerate(state['changes']):
        if original is not None:
            backup=workspace.audit_dir/('before-'+str(index))
            backup.write_bytes(original)
            change['backup']=str(backup.relative_to(workspace.root))
        workspace.changes[path]=change
    workspace.revision=state['revision']
    # Reads, syntax checks and test success must be obtained in this new run.
    if state['plan'] is not None:
        if workspace.planner is None:raise ValueError('checkpoint plan has no requirements')
        report=state['plan']
        if not isinstance(report,dict) or not isinstance(report.get('steps'),list):raise ValueError('invalid checkpoint plan')
        steps=report['steps']
        if type(report.get('revision')) is int and report['revision']==0 and not steps:
            # Requirements create an empty planner before the first set_plan.
            # Its obligations still come from the immutable requirements.
            workspace.planner._save('resumed_before_first_plan')
            return
        if type(report.get('revision')) is not int or not 1<=report['revision']<=1000:raise ValueError('invalid plan revision')
        if any(not isinstance(s,dict) or s.get('status') not in ('ready','blocked','completed') for s in steps):raise ValueError('invalid checkpoint step status')
        workspace.planner.set([{k:v for k,v in s.items() if k!='status'} for s in steps])
        workspace.planner.revision=report['revision']
        workspace.planner.completed={s['id'] for s in steps if s.get('status')=='completed'}
        workspace.planner.refresh()
        workspace.planner._save('resumed_and_revalidated')


def claim(workspace,identity):
    path=workspace.path('.breaktail-agent/'+identity+'/resume_claim.json',internal=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump({'child_run_id':workspace.run_id},stream)
