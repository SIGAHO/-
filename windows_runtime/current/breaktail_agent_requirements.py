"""Operator-supplied completion checks; never editable by model actions."""
import json
import hashlib
import math
import re


def normalize(workspace, value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)-{'goal','constraints','checks','plan_required'}:
        raise ValueError('requirements must contain only goal, constraints and checks')
    goal=value.get('goal')
    constraints=value.get('constraints',[])
    checks=value.get('checks')
    if type(value.get('plan_required',False)) is not bool:
        raise ValueError('plan_required must be a boolean')
    if not isinstance(goal,str) or not goal.strip() or len(goal)>4000:
        raise ValueError('requirements goal must be 1..4000 characters')
    if not isinstance(constraints,list) or len(constraints)>16 or any(not isinstance(x,str) or not x.strip() or len(x)>1000 for x in constraints):
        raise ValueError('constraints must be at most 16 nonempty strings')
    if not isinstance(checks,list) or not 1<=len(checks)<=16:
        raise ValueError('requirements must have 1..16 checks')
    fields={'file_exists':{'kind','path'},'text_contains':{'kind','path','text'},
            'json_equals':{'kind','path','pointer','expected'},
            'file_sha256':{'kind','path','sha256'}}
    for check in checks:
        if not isinstance(check,dict) or not isinstance(check.get('kind'),str) or check['kind'] not in fields or set(check)!=fields[check['kind']]:
            raise ValueError('unknown check or invalid check fields')
        workspace.path(check['path'])
        if check['kind']=='file_sha256' and (not isinstance(check['sha256'],str)
                or not re.fullmatch(r'[0-9a-f]{64}',check['sha256'])):
            raise ValueError('file_sha256 needs 64 lowercase hexadecimal characters')
        if check['kind']=='text_contains' and (not isinstance(check['text'],str) or not check['text'] or len(check['text'])>4000):
            raise ValueError('text_contains needs 1..4000 characters')
        if check['kind']=='json_equals':
            pointer=check['pointer']
            if not isinstance(pointer,str) or len(pointer)>1000 or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])',pointer):
                raise ValueError('invalid JSON pointer')
            expected=check['expected']
            if expected is not None and type(expected) not in (str,int,float,bool):
                raise ValueError('json_equals expected must be a JSON scalar')
            if isinstance(expected,str) and len(expected)>4000:
                raise ValueError('expected text is too long')
            if isinstance(expected,float) and not math.isfinite(expected):
                raise ValueError('expected number must be finite')
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))


def _at(value,pointer):
    if not pointer:return value
    for raw in pointer[1:].split('/'):
        key=raw.replace('~1','/').replace('~0','~')
        if isinstance(value,list):
            if not re.fullmatch(r'0|[1-9][0-9]*',key):raise ValueError('invalid array index')
            value=value[int(key)]
        elif isinstance(value,dict):value=value[key]
        else:raise ValueError('pointer traverses a scalar')
    return value


def verify(workspace, requirements):
    if requirements is None:return None
    results=[]
    for check in requirements['checks']:
        row={'kind':check['kind'],'path':check['path'],'passed':False}
        try:
            path=workspace.path(check['path'])
            if not path.is_file():raise ValueError('required file is missing')
            if check['kind']=='file_exists':row['passed']=True
            elif check['kind']=='file_sha256':
                with path.open('rb') as stream:data=stream.read(64001)
                if len(data)>64000:raise ValueError('check file exceeds 64KB')
                row['actual_sha256']=hashlib.sha256(data).hexdigest()
                row['passed']=row['actual_sha256']==check['sha256']
            else:
                if path.stat().st_size>64000:raise ValueError('check file exceeds 64KB')
                text=path.read_text(encoding='utf-8-sig')
                if check['kind']=='text_contains':row['passed']=check['text'] in text
                else:
                    actual=_at(json.loads(text),check['pointer'])
                    row['passed']=type(actual) is type(check['expected']) and actual==check['expected']
                    row['actual_type']=type(actual).__name__
                    row['actual_preview']=str(actual)[:240]
            row['reason']='matched' if row['passed'] else 'condition_not_met'
        except (OSError,ValueError,TypeError,KeyError,IndexError,UnicodeError) as error:
            row['reason']=type(error).__name__
        results.append(row)
    return {'passed':all(row['passed'] for row in results),'checks':results,
            'constraints_auto_verified':False}
