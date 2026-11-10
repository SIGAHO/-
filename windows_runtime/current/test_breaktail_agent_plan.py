import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_requirements import normalize


class PlanTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.requirements={'goal':'成果物を順番に作る','plan_required':True,'checks':[
            {'kind':'text_contains','path':'a.txt','text':'ready'},
            {'kind':'text_contains','path':'b.txt','text':'done'}]}
        self.steps=[{'id':'first','title':'最初のファイル','depends_on':[],'check_indices':[0]},
            {'id':'second','title':'次のファイル','depends_on':['first'],'check_indices':[1]}]
        self.ws=Workspace(self.root)
        self.ws.enable_planning(normalize(self.ws,self.requirements))

    def test_missing_plan_and_unverified_steps_cannot_finish(self):
        with self.assertRaises(ValueError):self.ws.planner.check_finish()
        self.ws.execute('set_plan',{'steps':self.steps})
        with self.assertRaises(ValueError):self.ws.execute('complete_step',{'id':'first'})
        (self.root/'a.txt').write_text('ready',encoding='utf-8')
        (self.root/'b.txt').write_text('done',encoding='utf-8')
        with self.assertRaises(ValueError):self.ws.execute('complete_step',{'id':'second'})
        self.ws.execute('complete_step',{'id':'first'})
        self.ws.execute('complete_step',{'id':'second'})
        self.ws.planner.check_finish()
        self.assertTrue((self.ws.audit_dir/'plan_history.jsonl').exists())

    def test_stale_artifact_invalidates_step_and_dependents(self):
        self.ws.planner.set(self.steps)
        (self.root/'a.txt').write_text('ready',encoding='utf-8')
        (self.root/'b.txt').write_text('done',encoding='utf-8')
        self.ws.planner.complete('first');self.ws.planner.complete('second')
        (self.root/'a.txt').write_text('wrong',encoding='utf-8')
        with self.assertRaises(ValueError):self.ws.planner.check_finish()
        self.assertEqual(self.ws.planner.completed,set())

    def test_dependencies_coverage_and_completed_rewrite_are_rejected(self):
        for changed in (
            [{**self.steps[0],'depends_on':['second']},self.steps[1]],
            [self.steps[0]],
            [self.steps[0],{**self.steps[1],'check_indices':[True]}]):
            with self.subTest(changed=changed),self.assertRaises(ValueError):self.ws.planner.set(changed)
        self.ws.planner.set(self.steps)
        (self.root/'a.txt').write_text('ready',encoding='utf-8')
        self.ws.planner.complete('first')
        revised=[self.steps[0],{**self.steps[1],'title':'未完工程を修正'}]
        self.ws.planner.set(revised)
        self.assertEqual(self.ws.planner.revision,2)
        with self.assertRaises(ValueError):
            self.ws.planner.set([{**self.steps[0],'title':'完了済を変更'},revised[1]])

    def test_plan_actions_run_through_actual_agent_loop(self):
        actions=iter([
            {'tool':'set_plan','args':{'steps':self.steps}},
            {'tool':'write_file','args':{'path':'a.txt','content':'ready'}},
            {'tool':'complete_step','args':{'id':'first'}},
            {'tool':'finish','args':{'summary':'早すぎる完了'}},
            {'tool':'write_file','args':{'path':'b.txt','content':'done'}},
            {'tool':'complete_step','args':{'id':'second'}},
            {'tool':'finish','args':{'summary':'両工程を確認'}}])
        result=run_agent({},self.root,'成果物を作る',requirements=self.requirements,
            model=lambda m:json.dumps(next(actions)),max_steps=7)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['acceptance']['passed'])
        self.assertEqual([s['status'] for s in result['plan']['steps']],['completed','completed'])

    def test_planning_tools_unavailable_without_requirements(self):
        ws=Workspace(self.root)
        self.assertNotIn('set_plan',ws.available_tools())
        with self.assertRaises(ValueError):ws.execute('set_plan',{'steps':self.steps})


if __name__=='__main__':unittest.main()
