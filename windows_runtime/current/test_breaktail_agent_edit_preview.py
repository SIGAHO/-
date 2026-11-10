import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_edit_preview import ReplacementSyntaxError


class EditPreviewTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_invalid_partial_edit_leaves_file_mtime_backup_revision_and_checks_intact(self):
        path=self.root/'cart.py'
        path.write_bytes(b'def total(values):\r\n    return sum(values)\r\n')
        ws=Workspace(self.root)
        ws.read('cart.py')
        ws.execute('check_python',{})
        original=path.read_bytes()
        stamp=path.stat().st_mtime_ns
        reads=dict(ws.reads)
        with self.assertRaises(ReplacementSyntaxError) as caught:
            ws.execute('replace_text',{'path':'cart.py','old':'return sum(values)',
                                      'new':'if not values:\nreturn 0\nreturn sum(values)'})
        observation=caught.exception.observation
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(path.stat().st_mtime_ns,stamp)
        self.assertEqual(ws.changes,{})
        self.assertEqual(ws.revision,0)
        self.assertEqual(ws.syntax_revision,0)
        self.assertEqual(ws.reads,reads)
        self.assertEqual(list(ws.audit_dir.glob('before-*')),[])
        self.assertFalse(observation['written'])
        self.assertEqual(observation['source'],'replacement_candidate_not_written')
        self.assertEqual(observation['error'],'IndentationError')

    def test_valid_edit_is_saved_with_original_backup_but_is_not_current_verification(self):
        path=self.root/'cart.py'
        path.write_text('def total(values):\n    return sum(values)\n',encoding='utf-8')
        original=path.read_bytes()
        ws=Workspace(self.root)
        ws.read('cart.py')
        result=ws.execute('replace_text',{'path':'cart.py','old':'sum(values)','new':'sum(values or [])'})
        self.assertTrue(result['written'])
        self.assertTrue(result['replacement_preview']['checked'])
        self.assertEqual(ws.revision,1)
        self.assertEqual(ws.syntax_revision,-1)
        self.assertEqual((ws.audit_dir/'before-0').read_bytes(),original)
        path.write_text('user changed',encoding='utf-8')
        with self.assertRaises(ValueError):ws.execute('replace_text',{'path':'cart.py','old':'changed','new':'edit'})
        self.assertEqual(path.read_text(),'user changed')

    def test_preexisting_invalid_source_and_nonpython_keep_literal_edit_contract(self):
        ws=Workspace(self.root)
        for name,content,old,new,reason in (
            ('broken.py','def total(:','total(:','total():\n return 0\n','original_syntax_invalid'),
            ('notes.txt','x=1','x=1','invalid Python {','not_python')):
            with self.subTest(name=name):
                (self.root/name).write_text(content,encoding='utf-8')
                ws.read(name)
                result=ws.execute('replace_text',{'path':name,'old':old,'new':new})
                self.assertTrue(result['written'])
                self.assertEqual(result['replacement_preview']['reason'],reason)
                self.assertEqual((self.root/name).read_text(encoding='utf-8'),content.replace(old,new))

    def test_agent_reports_unsaved_candidate_and_recovers_by_full_write(self):
        (self.root/'cart.py').write_text('def total(values):\n    return sum(values)\n',encoding='utf-8')
        actions=iter([
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'replace_text','args':{'path':'cart.py','old':'return sum(values)','new':'if not values:\nreturn 0\nreturn sum(values)'}},
            {'tool':'write_file','args':{'path':'cart.py','content':'def total(values):\n    return sum(values or [])\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'候補を直して確認'}}])
        result=run_agent({},self.root,'cart.pyを修正',model=lambda m:json.dumps(next(actions)),max_steps=5)
        self.assertEqual(result['status'],'completed')
        events=[json.loads(s) for s in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[1]['error'],'ReplacementSyntaxError')
        self.assertFalse(events[1]['replacement_preview']['written'])
        self.assertNotIn('syntax_observation',events[1])
        self.assertEqual(events[1]['revision'],0)
        self.assertEqual(result['revision'],1)


if __name__=='__main__':unittest.main()
