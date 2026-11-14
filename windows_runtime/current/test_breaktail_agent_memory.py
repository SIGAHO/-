import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace, run_agent
from breaktail_agent_memory import recall


class WorkMemoryTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent.parent / 'eval' / 'agent-unit'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def episode(self):
        actions = iter([
            {'tool': 'write_file', 'args': {'path': 'cart.py', 'content': 'def total(:'}},
            {'tool': 'check_python', 'args': {}},
            {'tool': 'write_file', 'args': {'path': 'cart.py', 'content': 'def total():\n return 1\n'}},
            {'tool': 'check_python', 'args': {}},
            {'tool': 'finish', 'args': {'summary': '修正済み'}}])
        return run_agent({}, self.root, 'cart.pyの合計を修正', max_steps=5,
            model=lambda _: json.dumps(next(actions)))

    def test_new_process_reads_relevant_failure_and_file_evidence(self):
        before = self.episode()
        captured = []
        def model(messages):
            captured.extend(messages)
            return json.dumps({'tool': 'finish', 'args': {'summary': '記録を確認'}})
        after = run_agent({}, self.root, 'cart.pyの合計を調べて', model=model)
        self.assertEqual(after['memory_recalled_runs'], [before['run_id']])
        recalled = json.loads(next(m['content'].split(': ', 1)[1] for m in captured if m['content'].startswith('WORK_MEMORY')))
        self.assertEqual(recalled[0]['previous_failures'][0]['error'], 'SyntaxError')
        self.assertTrue(recalled[0]['files'][0]['matches_previous_result'])
        self.assertFalse(after['syntax_verified'])
        self.assertFalse(after['tests_passed'])
        self.assertEqual(json.loads((Path(after['journal']) / 'memory_used.json').read_text(encoding='utf-8')), recalled)

    def test_changed_file_is_marked_stale_without_modification(self):
        self.episode()
        (self.root / 'cart.py').write_text('x=999', encoding='utf-8')
        episodes = recall(Workspace(self.root), 'cart.pyを修正')
        self.assertFalse(episodes[0]['files'][0]['matches_previous_result'])
        self.assertEqual((self.root / 'cart.py').read_text(), 'x=999')

    def test_no_cross_workspace_or_irrelevant_task_recall(self):
        self.episode()
        self.assertEqual(recall(Workspace(self.root), '音楽について'), [])
        other = self.root / 'another'
        other.mkdir()
        self.assertEqual(recall(Workspace(other), 'cart.pyを修正'), [])

    def test_corrupt_journal_does_not_break_work(self):
        before = self.episode()
        (Path(before['journal']) / 'result.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(recall(Workspace(self.root), 'cart.pyを修正'), [])

    def test_previous_pass_never_bypasses_current_verification(self):
        before = self.episode()
        result_path = Path(before['journal']) / 'result.json'
        result = json.loads(result_path.read_text(encoding='utf-8'))
        result['tests_passed'] = True
        result_path.write_text(json.dumps(result), encoding='utf-8')
        actions = iter([
            {'tool': 'read_file', 'args': {'path': 'cart.py'}},
            {'tool': 'write_file', 'args': {'path': 'cart.py', 'content': 'x=2'}},
            {'tool': 'finish', 'args': {'summary': '以前成功済みなので完了'}}])
        after = run_agent({}, self.root, 'cart.pyの合計を修正', max_steps=3,
            model=lambda _: json.dumps(next(actions)))
        self.assertEqual(after['status'], 'step_limit')
        self.assertFalse(after['syntax_verified'])


if __name__ == '__main__':
    unittest.main()
