import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import run_agent


class ResumeTests(unittest.TestCase):
    def test_identical_repeated_write_is_noop_but_requires_fresh_read(self):
        from breaktail_agent import Workspace
        path=self.root/'already.txt'
        path.write_text('same',encoding='utf-8')
        ws=Workspace(self.root)
        with self.assertRaises(ValueError):ws.write('already.txt','same')
        ws.read('already.txt')
        stamp=path.stat().st_mtime_ns
        result=ws.write('already.txt','same')
        self.assertFalse(result['written'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(path.stat().st_mtime_ns,stamp)
        self.assertEqual(ws.revision,0)
        self.assertEqual(ws.changes,{})

    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.requirements={'goal':'2ファイルを作る','plan_required':True,'checks':[
            {'kind':'text_contains','path':'a.txt','text':'ready'},
            {'kind':'text_contains','path':'b.txt','text':'done'}]}
        self.steps=[{'id':'first','title':'aを作る','depends_on':[],'check_indices':[0]},
            {'id':'second','title':'bを作る','depends_on':['first'],'check_indices':[1]}]

    def partial(self,allow_execution=False):
        actions=iter([
            {'tool':'set_plan','args':{'steps':self.steps}},
            {'tool':'write_file','args':{'path':'a.txt','content':'ready'}},
            {'tool':'complete_step','args':{'id':'first'}}])
        return run_agent({},self.root,'2ファイルを作る',requirements=self.requirements,
            allow_execution=allow_execution,model=lambda m:json.dumps(next(actions)),max_steps=3)

    def test_resume_retains_conditions_plan_and_does_not_replay_completed_write(self):
        before=self.partial(allow_execution=True)
        source_stat=(self.root/'a.txt').stat().st_mtime_ns
        actions=iter([
            {'tool':'write_file','args':{'path':'b.txt','content':'done'}},
            {'tool':'complete_step','args':{'id':'second'}},
            {'tool':'finish','args':{'summary':'残りだけ完了'}}])
        captured=[]
        def model(messages):
            captured[:]=messages
            return json.dumps(next(actions))
        after=run_agent({},self.root,resume_run_id=before['run_id'],model=model,max_steps=3)
        self.assertEqual(after['status'],'completed')
        self.assertEqual(after['resumed_from'],before['run_id'])
        self.assertFalse(after['execution_enabled'])
        self.assertEqual((self.root/'a.txt').stat().st_mtime_ns,source_stat)
        self.assertEqual(after['plan']['steps'][0]['status'],'completed')
        self.assertTrue(any(m['content'].startswith('RESUME_STATE') for m in captured))
        called=[]
        with self.assertRaises(ValueError):
            run_agent({},self.root,resume_run_id=before['run_id'],model=lambda m:called.append(m))
        self.assertEqual(called,[])

    def test_conflicting_file_and_modified_requirements_refuse_before_model(self):
        before=self.partial()
        (self.root/'a.txt').write_text('user changed',encoding='utf-8')
        called=[]
        with self.assertRaises(ValueError):
            run_agent({},self.root,resume_run_id=before['run_id'],model=lambda m:called.append(m))
        self.assertEqual(called,[])
        self.assertEqual((self.root/'a.txt').read_text(),'user changed')
        (self.root/'a.txt').write_text('ready',encoding='utf-8')
        path=Path(before['journal'])/'requirements.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        data['checks'][0]['text']='weakened'
        path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):
            run_agent({},self.root,resume_run_id=before['run_id'],model=lambda m:called.append(m))
        self.assertEqual(called,[])

    def test_reads_and_backup_are_restored_safely_across_multiple_resumes(self):
        (self.root/'x.txt').write_text('original',encoding='utf-8')
        actions=iter([{'tool':'read_file','args':{'path':'x.txt'}},
                      {'tool':'write_file','args':{'path':'x.txt','content':'first'}}])
        first=run_agent({},self.root,'xを修正',model=lambda m:json.dumps(next(actions)),max_steps=2)
        actions=iter([
            {'tool':'write_file','args':{'path':'x.txt','content':'must refuse without fresh read'}},
            {'tool':'read_file','args':{'path':'x.txt'}},
            {'tool':'write_file','args':{'path':'x.txt','content':'second'}}])
        second=run_agent({},self.root,resume_run_id=first['run_id'],model=lambda m:json.dumps(next(actions)),max_steps=3)
        self.assertEqual((self.root/'x.txt').read_text(),'second')
        events=[json.loads(x) for x in (Path(second['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[0]['error'],'ValueError')
        self.assertEqual((self.root/second['changes'][0]['backup']).read_text(),'original')
        third=run_agent({},self.root,resume_run_id=second['run_id'],
            model=lambda m:json.dumps({'tool':'finish','args':{'summary':'変更状態を確認'}}))
        self.assertEqual(third['status'],'completed')
        self.assertEqual((self.root/third['changes'][0]['backup']).read_text(),'original')

    def test_completed_runs_and_replacement_task_are_not_resumable(self):
        before=self.partial()
        with self.assertRaises(ValueError):
            run_agent({},self.root,'別の依頼',resume_run_id=before['run_id'])
        with self.assertRaises(ValueError):
            run_agent({},self.root,resume_run_id=before['run_id'],requirements=self.requirements)
        completed=run_agent({},self.root,'調査',model=lambda m:json.dumps({'tool':'finish','args':{'summary':'調査完了'}}))
        with self.assertRaises(ValueError):run_agent({},self.root,resume_run_id=completed['run_id'])
        with self.assertRaises(ValueError):run_agent({},self.root,resume_run_id='../outside')

    def test_resume_before_first_plan_keeps_required_plan_and_all_checks(self):
        first=run_agent({},self.root,'2ファイルを作る',requirements=self.requirements,max_steps=1,
                        model=lambda m:json.dumps({'tool':'list_files','args':{}}))
        self.assertEqual(first['plan']['revision'],0)
        actions=iter([
            {'tool':'finish','args':{'summary':'計画なしの完了を試す'}},
            {'tool':'set_plan','args':{'steps':self.steps}},
            {'tool':'write_file','args':{'path':'a.txt','content':'ready'}},
            {'tool':'complete_step','args':{'id':'first'}},
            {'tool':'write_file','args':{'path':'b.txt','content':'done'}},
            {'tool':'complete_step','args':{'id':'second'}},
            {'tool':'finish','args':{'summary':'元の計画条件を全て検証'}}])
        second=run_agent({},self.root,resume_run_id=first['run_id'],max_steps=7,model=lambda m:json.dumps(next(actions)))
        self.assertEqual(second['status'],'completed')
        self.assertTrue(second['plan']['required'])
        self.assertTrue(second['acceptance']['passed'])
        events=[json.loads(s) for s in (Path(second['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertIn('set_plan is required',events[0]['detail'])


if __name__=='__main__':unittest.main()
