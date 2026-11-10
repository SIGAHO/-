"""Cooperative stop requests and an elapsed-time budget, owned by the operator."""
import json
import math
import re
import time


class RunStopped(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__(status)


class RunControl:
    def __init__(self,workspace,started,max_seconds):
        if type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or not .01<=max_seconds<=3600:
            raise ValueError('max_seconds must be 0.01..3600')
        self.workspace=workspace
        self.deadline=started+max_seconds

    def status(self):
        marker=self.workspace.audit_dir/'cancel.requested'
        if marker.exists() or marker.is_symlink():return 'cancelled'
        if time.monotonic()>=self.deadline:return 'time_limit'
        return None

    def check(self):
        status=self.status()
        if status:raise RunStopped(status)

    def timeout(self,maximum):
        return max(.001,min(maximum,self.deadline-time.monotonic()))


def request_cancel(workspace,identity):
    if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):
        raise ValueError('cancel run id must be 32 lowercase hexadecimal characters')
    prefix='.breaktail-agent/'+identity
    task=workspace.path(prefix+'/task.json',internal=True)
    if not task.is_file() or task.stat().st_size>256000:raise ValueError('invalid cancel target')
    saved=json.loads(task.read_text(encoding='utf-8'))
    if not isinstance(saved,dict) or saved.get('workspace')!=str(workspace.root):
        raise ValueError('cancel target belongs to a different workspace')
    if workspace.path(prefix+'/result.json',internal=True).exists():
        return {'run_id':identity,'status':'already_settled'}
    marker=workspace.path(prefix+'/cancel.requested',internal=True)
    try:
        with marker.open('x',encoding='utf-8') as stream:stream.write('operator requested cancellation\n')
    except FileExistsError:pass
    return {'run_id':identity,'status':'cancel_requested'}
