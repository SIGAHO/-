import copy
import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_memory import recall
from breaktail_agent_lessons import observed_recoveries


class RecoveryMemoryTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def run_actions(self,actions,**kwargs):
        sequence=iter(actions)
        return run_agent({},self.root,'cart.py の合計を修正',max_steps=len(actions),
                         model=lambda m:json.dumps(next(sequence)),**kwargs)

    def syntax_recovery(self):
        return self.run_actions([
            {'tool':'write_file','args':{'path':'cart.py','content':'def total(:'}},
            {'tool':'check_python','args':{}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total():\n return 1\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'構文の再確認'}}])

    def records(self,result):
        return [json.loads(line) for line in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_syntax_failure_edit_and_pass_have_sources_without_inferred_cause(self):
        result=self.syntax_recovery()
        events=self.records(result)
        lesson=observed_recoveries(Workspace(self.root),events,result)[0]
        self.assertEqual((lesson['failure_step'],lesson['edit_steps'],lesson['passed_step']),(2,[3],4))
        self.assertEqual(lesson['edited_paths'],['cart.py'])
        self.assertFalse(lesson['cause_inferred'])
        self.assertTrue(lesson['current_checks_required'])
        self.assertEqual(events[1]['tool'],'check_python')
        self.assertTrue(events[1]['verification']['stable_during_check'])
        recalled=recall(Workspace(self.root),'cart.pyの類題')
        self.assertEqual(recalled[0]['observed_recoveries'],[lesson])
        (self.root/'new_input.py').write_text('x=1',encoding='utf-8')
        self.assertFalse(recall(Workspace(self.root),'cart.pyの類題')[0]['observed_recoveries'][0]['current_python_inputs_match'])
        (self.root/'cart.py').write_text('x=2',encoding='utf-8')
        stale=recall(Workspace(self.root),'cart.pyの類題')[0]['observed_recoveries'][0]
        self.assertFalse(stale['current_python_inputs_match'])

    def test_missing_evidence_unfinished_and_inconsistent_final_hash_never_certify(self):
        result=self.syntax_recovery()
        events=self.records(result)
        ws=Workspace(self.root)
        for mutation in ('legacy','unstable','unfinished','hash','order','no_edit'):
            candidate=copy.deepcopy(events)
            report=copy.deepcopy(result)
            if mutation=='legacy':candidate[1].pop('verification')
            elif mutation=='unstable':candidate[3]['verification']['stable_during_check']=False
            elif mutation=='unfinished':report['status']='step_limit'
            elif mutation=='hash':report['changes'][0]['after_sha256']='0'*64
            elif mutation=='order':candidate[2]['step']=1
            elif mutation=='no_edit':candidate[2]['result']['written']=False
            with self.subTest(mutation=mutation):self.assertEqual(observed_recoveries(ws,candidate,report),[])

    def test_real_failed_tests_then_fix_and_recheck_unchanged_tests(self):
        (self.root/'cart.py').write_text('def total(values):\n return sum(values)\n',encoding='utf-8')
        (self.root/'test_cart.py').write_text('import unittest\nfrom cart import total\nclass Tests(unittest.TestCase):\n def test_none(self): self.assertEqual(total(None),0)\n',encoding='utf-8')
        result=self.run_actions([
            {'tool':'run_tests','args':{}},
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'replace_text','args':{'path':'cart.py','old':'sum(values)','new':'sum(values or [])'}},
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'実際のテストを再確認'}}],allow_execution=True)
        self.assertEqual(result['status'],'completed')
        events=self.records(result)
        ws=Workspace(self.root)
        lesson=observed_recoveries(ws,events,result)[0]
        self.assertEqual((lesson['failure_step'],lesson['passed_step']),(1,5))
        self.assertTrue(lesson['test_files_unchanged'])
        for mutation in ('test_changed','empty','timeout','wrong_check'):
            candidate=copy.deepcopy(events)
            if mutation=='test_changed':candidate[4]['verification']['files']['test_cart.py']='0'*64
            elif mutation=='empty':candidate[0]['result']['output']='TEST_COUNT=0\n'
            elif mutation=='timeout':candidate[0]['result']['timeout']=True
            elif mutation=='wrong_check':candidate[4]['tool']='check_python'
            with self.subTest(mutation=mutation):self.assertEqual(observed_recoveries(ws,candidate,result),[])

    def test_recall_does_not_bypass_new_checks_or_repeat_sensitive_error_text(self):
        first=self.syntax_recovery()
        event_path=Path(first['journal'])/'events.jsonl'
        events=self.records(first)
        events[1]['detail']='SENSITIVE_EXCEPTION_TEXT'
        event_path.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        second=self.run_actions([{'tool':'finish','args':{'summary':'記憶を確認'}}])
        used=(Path(second['journal'])/'memory_used.json').read_text(encoding='utf-8')
        self.assertIn('observed_recoveries',used)
        self.assertNotIn('SENSITIVE_EXCEPTION_TEXT',used)
        self.assertFalse(second['syntax_verified'])
        self.assertFalse(second['tests_passed'])

    def test_invalid_tool_type_is_a_recorded_failure(self):
        result=self.run_actions([{'tool':[],'args':{}}])
        self.assertEqual(result['status'],'step_limit')
        self.assertEqual(self.records(result)[0]['error'],'ValueError')

    def test_indentation_and_tab_error_repairs_are_not_lost(self):
        for kind,source in (
            ('IndentationError','def total():\nreturn 1\n'),
            ('TabError','def total():\n\tpass\n        pass\n')):
            with self.subTest(kind=kind):
                (self.root/'cart.py').write_text(source,encoding='utf-8')
                result=self.run_actions([
                    {'tool':'check_python','args':{}},
                    {'tool':'read_file','args':{'path':'cart.py'}},
                    {'tool':'write_file','args':{'path':'cart.py','content':'def total():\n return 1\n'}},
                    {'tool':'check_python','args':{}},
                    {'tool':'finish','args':{'summary':'字下げも再検証'}}])
                events=self.records(result)
                self.assertEqual(events[0]['error'],kind)
                lesson=observed_recoveries(Workspace(self.root),events,result)[0]
                self.assertEqual((lesson['failure_step'],lesson['passed_step']),(1,4))
                self.assertFalse(lesson['cause_inferred'])


if __name__=='__main__':unittest.main()
