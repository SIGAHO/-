import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_diagnostics import SyntaxFeedback


class SyntaxFeedbackTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def run_actions(self,actions,**kwargs):
        actions=iter(actions)
        return run_agent({},self.root,'cart.pyを修正',model=lambda m:json.dumps(next(actions)),**kwargs)

    def stalled(self):
        (self.root/'cart.py').write_text('def total():\n return (\n',encoding='utf-8')
        return self.run_actions([
            {'tool':'check_python','args':{}},
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'check_python','args':{}},
            {'tool':'check_python','args':{}},
            {'tool':'write_file','args':{'path':'should_not_exist.txt','content':'wrong'}}])

    def test_current_source_indent_and_repeat_stop_are_saved_before_more_actions(self):
        result=self.stalled()
        self.assertEqual(result['status'],'stalled')
        self.assertEqual(result['steps'],4)
        self.assertFalse((self.root/'should_not_exist.txt').exists())
        events=[json.loads(s) for s in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        observations=[e['syntax_observation'] for e in events if 'syntax_observation' in e]
        self.assertEqual([o['unchanged_failure_count'] for o in observations],[1,2,3])
        self.assertEqual(observations[0]['path'],'cart.py')
        self.assertEqual(observations[0]['lines'][1]['leading_whitespace'],' ')
        self.assertTrue(observations[0]['matches_checked_input'])
        self.assertFalse(result['syntax_verified'])

    def test_stalled_run_can_resume_with_fresh_read_fix_and_recheck(self):
        first=self.stalled()
        second=self.run_actions([
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total():\n return 0\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'再検証済み'}}],resume_run_id=first['run_id'])
        self.assertEqual(second['status'],'completed')
        self.assertTrue(second['syntax_verified'])
        self.assertIn(first['run_id'],second['memory_recalled_runs'])
        self.assertFalse(second['execution_enabled'])

    def test_different_inputs_reset_counter_and_fix_can_complete(self):
        (self.root/'cart.py').write_text('def total():\n return (\n',encoding='utf-8')
        result=self.run_actions([
            {'tool':'check_python','args':{}},
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total():\n return [\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total():\n return 0\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'修正済み'}}])
        self.assertEqual(result['status'],'completed')
        events=[json.loads(s) for s in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['syntax_observation']['unchanged_failure_count'] for e in events if 'syntax_observation' in e],[1,1])

    def test_protected_paths_stale_inputs_and_long_lines_do_not_leak_or_stall(self):
        ws=Workspace(self.root)
        feedback=SyntaxFeedback()
        denied=feedback.observe(ws,SyntaxError('bad',('.env/secret.py',1,1,'secret')), {})
        self.assertTrue(denied['unavailable'])
        self.assertNotIn('lines',denied)
        (self.root/'long.py').write_text('x='+('a'*400)+'\\n',encoding='utf-8')
        error=SyntaxError('bad',('long.py',1,3,'untrusted error.text'))
        stale=feedback.observe(ws,error,{'long.py':'0'*64})
        self.assertFalse(stale['matches_checked_input'])
        self.assertNotIn('unchanged_failure_count',stale)
        current=feedback.observe(ws,error,ws.verification_snapshot())
        self.assertEqual(current['unchanged_failure_count'],1)
        self.assertTrue(current['lines'][0]['truncated'])
        self.assertLessEqual(len(current['lines'][0]['text']),240)

    def test_reintroducing_same_error_after_success_starts_a_new_sequence(self):
        bad='def total():\n return (\n'
        good='def total():\n return 0\n'
        (self.root/'cart.py').write_text(bad,encoding='utf-8')
        result=self.run_actions([
            {'tool':'check_python','args':{}},
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'write_file','args':{'path':'cart.py','content':good}},
            {'tool':'check_python','args':{}},
            {'tool':'write_file','args':{'path':'cart.py','content':bad}},
            {'tool':'check_python','args':{}},
            {'tool':'write_file','args':{'path':'cart.py','content':good}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'修正後の再導入も区別'}}])
        self.assertEqual(result['status'],'completed')
        events=[json.loads(s) for s in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['syntax_observation']['unchanged_failure_count'] for e in events if 'syntax_observation' in e],[1,1])


if __name__=='__main__':unittest.main()
