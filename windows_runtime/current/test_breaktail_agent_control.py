import json
from pathlib import Path
import tempfile
import time
import unittest

from breaktail_agent import Workspace,run_agent,request_cancel


class ControlTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_cancel_after_model_returns_prevents_pending_write(self):
        called=[]
        def model(messages):
            task_path=next(self.root.glob('.breaktail-agent/*/task.json'))
            response=request_cancel(Workspace(self.root,create_audit=False),task_path.parent.name)
            self.assertEqual(response['status'],'cancel_requested')
            called.append(1)
            return json.dumps({'tool':'write_file','args':{'path':'must_not_exist.txt','content':'x'}})
        result=run_agent({},self.root,'作業',model=model)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(len(called),1)
        self.assertFalse((self.root/'must_not_exist.txt').exists())
        self.assertEqual(json.loads((Path(result['journal'])/'result.json').read_text(encoding='utf-8'))['status'],'cancelled')

    def test_elapsed_limit_prevents_action_and_explicit_resume_is_possible(self):
        def slow(messages):
            time.sleep(.03)
            return json.dumps({'tool':'write_file','args':{'path':'late.txt','content':'x'}})
        before=run_agent({},self.root,'作業',model=slow,max_seconds=.01)
        self.assertEqual(before['status'],'time_limit')
        self.assertFalse((self.root/'late.txt').exists())
        after=run_agent({},self.root,resume_run_id=before['run_id'],
            model=lambda m:json.dumps({'tool':'finish','args':{'summary':'再確認して終了'}}))
        self.assertEqual(after['status'],'completed')
        self.assertFalse(after['execution_enabled'])

    def test_cancel_settled_and_invalid_id_do_not_create_extra_run(self):
        result=run_agent({},self.root,'作業',model=lambda m:json.dumps({'tool':'finish','args':{'summary':'確認'}}))
        control_ws=Workspace(self.root,create_audit=False)
        count=len(list((self.root/'.breaktail-agent').iterdir()))
        self.assertEqual(request_cancel(control_ws,result['run_id'])['status'],'already_settled')
        with self.assertRaises(ValueError):request_cancel(control_ws,'../outside')
        self.assertEqual(len(list((self.root/'.breaktail-agent').iterdir())),count)

    def test_invalid_budget_is_rejected(self):
        for value in (0,-1,True,float('inf'),float('nan'),3601):
            with self.subTest(value=value),self.assertRaises(ValueError):
                run_agent({},self.root,'作業',max_seconds=value)


if __name__=='__main__':unittest.main()
