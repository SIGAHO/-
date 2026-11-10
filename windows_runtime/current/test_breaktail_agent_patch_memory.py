import copy
import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_memory import recall
from breaktail_agent_patch_memory import augment


class PatchMemoryTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def episode(self,extra=''):
        (self.root/'cart.py').write_text('def total(values):\n return sum(values)\n',encoding='utf-8')
        (self.root/'test_cart.py').write_text('import unittest\nfrom cart import total\nclass Tests(unittest.TestCase):\n def test_none(self): self.assertEqual(total(None),0)\n',encoding='utf-8')
        actions=iter([
            {'tool':'run_tests','args':{}},
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total(values):\n return sum(values or [])\n'+extra}},
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'修正後のテスト成功'}}])
        run=run_agent({},self.root,'cart.pyの合計を修正',model=lambda m:json.dumps(next(actions)),max_steps=6,allow_execution=True)
        self.assertEqual(run['status'],'completed')
        ws=Workspace(self.root,create_audit=False)
        return ws,run,recall(ws,'cart.pyの合計の類題',limit=1)

    def test_owned_verified_small_change_has_sources_and_default_is_unchanged(self):
        ws,run,episodes=self.episode()
        before=copy.deepcopy(episodes)
        augmented=augment(ws,episodes)
        self.assertEqual(episodes,before)
        self.assertNotIn('verified_change_examples',recall(ws,'cart.pyの合計の類題',limit=1)[0])
        example=augmented[0]['verified_change_examples'][0]
        self.assertIn('- return sum(values)',example['patch'])
        self.assertIn('+ return sum(values or [])',example['patch'])
        self.assertFalse(example['cause_inferred'])
        self.assertTrue(example['current_checks_required'])
        self.assertEqual(example['before_scope'],'run_start_not_failure_snapshot')
        self.assertEqual(example['instruction_authority'],'none')

    def test_changed_source_tests_and_backup_decline(self):
        ws,run,episodes=self.episode()
        for name in ('cart.py','test_cart.py',run['changes'][0]['backup']):
            path=ws.path(name,internal=True)
            original=path.read_bytes()
            path.write_bytes(original+b'\n# changed\n')
            with self.subTest(name=name):self.assertNotIn('verified_change_examples',augment(ws,episodes)[0])
            path.write_bytes(original)

    def test_forged_ownership_and_foreign_backup_decline(self):
        ws,run,episodes=self.episode()
        forged=copy.deepcopy(episodes)
        forged[0]['source']='../outside/result.json'
        self.assertNotIn('verified_change_examples',augment(ws,forged)[0])
        result_path=Path(run['journal'])/'result.json'
        original=json.loads(result_path.read_text(encoding='utf-8'))
        for mutation in ('workspace','backup','status'):
            candidate=copy.deepcopy(original)
            if mutation=='workspace':candidate['workspace']='another project'
            elif mutation=='backup':candidate['changes'][0]['backup']='../outside'
            else:candidate['status']='step_limit'
            result_path.write_text(json.dumps(candidate),encoding='utf-8')
            with self.subTest(mutation=mutation):self.assertNotIn('verified_change_examples',augment(ws,episodes)[0])
        result_path.write_text(json.dumps(original),encoding='utf-8')

    def test_large_examples_and_context_budget_are_not_truncated_into_other_claims(self):
        ws,run,episodes=self.episode(extra='# detail\n'*30)
        self.assertNotIn('verified_change_examples',augment(ws,episodes)[0])
        ws,run,episodes=self.episode()
        episodes[0]['padding']='x'*3900
        self.assertNotIn('verified_change_examples',augment(ws,episodes)[0])


if __name__=='__main__':unittest.main()
