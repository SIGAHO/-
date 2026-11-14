import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import breaktail_agent
from breaktail_agent import Workspace,run_agent


class CurrentVerificationTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'app.py').write_text('VALUE=1\n',encoding='utf-8')
        (self.root/'test_app.py').write_text('import unittest\nclass Tests(unittest.TestCase):\n def test_pass(self): self.assertTrue(True)\n',encoding='utf-8')

    def test_external_edits_additions_and_removals_invalidate_old_success(self):
        for kind in ('edit','add','remove'):
            with self.subTest(kind=kind):
                ws=Workspace(self.root,allow_execution=True)
                ws.execute('check_python',{})
                self.assertTrue(ws.execute('run_tests',{})['ok'])
                if kind=='edit':(self.root/'app.py').write_text('VALUE=2\n',encoding='utf-8')
                elif kind=='add':(self.root/'added.py').write_text('EXTRA=1\n',encoding='utf-8')
                else:(self.root/'added.py').unlink()  # Fixture owned by this test only.
                with self.assertRaises(ValueError):ws.verify_current_inputs()
                self.assertEqual(ws.verification_state(),{'syntax_verified':False,'tests_passed':False})
                self.assertEqual(ws.revision,0)
                self.assertEqual(ws.changes,{})

    def test_passing_test_process_that_changes_python_is_not_verified_until_rechecked(self):
        (self.root/'test_app.py').write_text('import unittest\nfrom pathlib import Path\nclass Tests(unittest.TestCase):\n def test_mutate(self):\n  Path(__file__).with_name("app.py").write_text("VALUE=2\\n",encoding="utf-8")\n  self.assertTrue(True)\n',encoding='utf-8')
        ws=Workspace(self.root,allow_execution=True)
        ws.execute('check_python',{})
        result=ws.execute('run_tests',{})
        self.assertTrue(result['process_ok'])
        self.assertEqual(result['exit_code'],0)
        self.assertFalse(result['ok'])
        self.assertFalse(result['inputs_stable'])
        self.assertIsNone(ws.test_inputs)
        with self.assertRaises(ValueError):ws.verify_current_inputs()
        self.assertFalse(ws.verification_state()['tests_passed'])
        ws.execute('check_python',{})
        self.assertTrue(ws.execute('run_tests',{})['ok'])
        ws.verify_current_inputs()
        self.assertTrue(ws.verification_state()['syntax_verified'])
        self.assertTrue(ws.verification_state()['tests_passed'])

    def test_failed_rerun_cannot_keep_an_earlier_passing_snapshot(self):
        ws=Workspace(self.root,allow_execution=True)
        self.assertTrue(ws.execute('run_tests',{})['ok'])
        self.assertIsNotNone(ws.test_inputs)
        (self.root/'test_app.py').write_text('import unittest\nclass Tests(unittest.TestCase):\n def test_fail(self): self.fail("expected")\n',encoding='utf-8')
        self.assertFalse(ws.execute('run_tests',{})['ok'])
        self.assertIsNone(ws.test_inputs)
        self.assertEqual(ws.tests_revision,-1)
        self.assertFalse(ws.verification_state()['tests_passed'])

    def test_change_during_syntax_parse_is_rejected_and_can_be_rechecked(self):
        ws=Workspace(self.root)
        original_parse=breaktail_agent.ast.parse
        changed=False
        def parse(source,*args,**kwargs):
            nonlocal changed
            if not changed:
                changed=True
                (self.root/'app.py').write_text('VALUE=3\n',encoding='utf-8')
            return original_parse(source,*args,**kwargs)
        with patch.object(breaktail_agent.ast,'parse',side_effect=parse):
            with self.assertRaises(ValueError):ws.execute('check_python',{})
        self.assertIsNone(ws.syntax_inputs)
        self.assertEqual(ws.syntax_revision,-1)
        with self.assertRaises(ValueError):ws.verify_current_inputs()
        ws.execute('check_python',{})
        ws.verify_current_inputs()
        self.assertTrue(ws.verification_state()['syntax_verified'])

    def test_finish_refuses_external_change_then_rechecks_and_saves_evidence(self):
        sequence=iter([
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'古い検査で終了を試す'}},
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'現在の内容を再検証'}}])
        calls=0
        def model(messages):
            nonlocal calls
            calls+=1
            if calls==3:(self.root/'new_input.py').write_text('NEW=1\n',encoding='utf-8')
            return json.dumps(next(sequence))
        result=run_agent({},self.root,'検査して報告',model=model,max_steps=6,allow_execution=True)
        self.assertEqual(result['status'],'completed')
        events=[json.loads(s) for s in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[2]['tool'],'finish')
        self.assertEqual(events[2]['error'],'ValueError')
        self.assertIn('Python inputs changed',events[2]['detail'])
        self.assertTrue(result['syntax_verified'])
        self.assertTrue(result['tests_passed'])
        self.assertIn('new_input.py',result['verification_inputs']['syntax'])
        self.assertEqual(result['verification_inputs']['syntax'],result['verification_inputs']['tests'])
        self.assertEqual(result['verification_inputs']['stale_checks'],[])


if __name__=='__main__':unittest.main()
