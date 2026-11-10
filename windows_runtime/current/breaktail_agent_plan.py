"""Small dependency plan whose completed steps need actual artifact evidence."""
import json
import os
import re

from breaktail_agent_requirements import verify


class WorkPlan:
    def __init__(self,workspace,requirements):
        self.workspace=workspace
        self.requirements=requirements
        self.steps=[]
        self.completed=set()
        self.revision=0

    def report(self):
        return {'revision':self.revision,'required':self.requirements.get('plan_required',False),
            'steps':[{**step,'status':('completed' if step['id'] in self.completed else
                      'ready' if set(step['depends_on'])<=self.completed else 'blocked')}
                     for step in self.steps]}

    def _save(self,reason,evidence=None):
        row={**self.report(),'reason':reason,'evidence':evidence}
        target=self.workspace.audit_dir/'plan.json'
        temp=self.workspace.audit_dir/'plan.tmp'
        temp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,target)
        with (self.workspace.audit_dir/'plan_history.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')

    def _verify(self,step):
        return verify(self.workspace,{'checks':[self.requirements['checks'][i] for i in step['check_indices']]})

    def refresh(self):
        invalid=[]
        for step in self.steps:
            if step['id'] in self.completed and (not set(step['depends_on'])<=self.completed or not self._verify(step)['passed']):
                self.completed.remove(step['id'])
                invalid.append(step['id'])
        if invalid:self._save('completed_evidence_became_stale',invalid)

    def set(self,steps):
        if not isinstance(steps,list) or not 1<=len(steps)<=12:
            raise ValueError('plan needs 1..12 steps')
        seen=set()
        covered=set()
        for step in steps:
            if not isinstance(step,dict) or set(step)!={'id','title','depends_on','check_indices'}:
                raise ValueError('step needs id, title, depends_on and check_indices')
            identity=step['id']
            if not isinstance(identity,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',identity) or identity in seen:
                raise ValueError('step id must be unique lowercase identifier')
            if not isinstance(step['title'],str) or not step['title'].strip() or len(step['title'])>240:
                raise ValueError('step title must be 1..240 characters')
            deps=step['depends_on']
            if not isinstance(deps,list) or any(not isinstance(x,str) or x not in seen for x in deps) or len(deps)!=len(set(deps)):
                raise ValueError('dependencies must refer to earlier steps only')
            indices=step['check_indices']
            if not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<len(self.requirements['checks']) for i in indices) or len(indices)!=len(set(indices)):
                raise ValueError('step checks must reference existing requirement indices')
            seen.add(identity)
            covered.update(indices)
        if covered!=set(range(len(self.requirements['checks']))):
            raise ValueError('plan must cover every operator completion check')
        self.refresh()
        replacement={step['id']:step for step in steps}
        for step in self.steps:
            if step['id'] in self.completed and replacement.get(step['id'])!=step:
                raise ValueError('cannot remove or rewrite a completed step')
        self.steps=json.loads(json.dumps(steps,ensure_ascii=False))
        self.revision+=1
        self._save('plan_set_or_revised')
        return self.report()

    def complete(self,identity):
        self.refresh()
        step=next((s for s in self.steps if s['id']==identity),None)
        if step is None:raise ValueError('unknown plan step')
        if not set(step['depends_on'])<=self.completed:
            raise ValueError('step dependencies are not completed')
        evidence=self._verify(step)
        if not evidence['passed']:
            self._save('step_verification_failed',{'id':identity,**evidence})
            raise ValueError('step conditions failed: '+json.dumps(evidence,ensure_ascii=False))
        self.completed.add(identity)
        self._save('step_verified',{'id':identity,**evidence})
        return self.report()

    def check_finish(self):
        self.refresh()
        if not self.steps:
            if self.requirements.get('plan_required',False):raise ValueError('set_plan is required before finish')
            return
        if len(self.completed)!=len(self.steps):
            raise ValueError('complete and verify every plan step before finish')
