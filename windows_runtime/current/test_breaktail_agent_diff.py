from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from breaktail_agent import Workspace


class ChangeReviewTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.ws=Workspace(self.root)

    def edit(self,name,before,after):
        (self.root/name).write_bytes(before)
        self.ws.read(name)
        self.ws.write(name,after)

    def test_registry_reviews_original_to_latest_without_modifying_or_granting_checks(self):
        self.edit('notes.txt','元\n'.encode(),'中\n')
        self.ws.write('notes.txt','最後\n')
        self.ws.write('new.txt','新規\n')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        revision=self.ws.revision
        reviewed=self.ws.execute('review_changes',{})
        self.assertEqual(reviewed['total_tracked'],2)
        first,second=reviewed['changes']
        self.assertEqual(first['status'],'modified')
        self.assertIn('-元\n',first['diff'])
        self.assertIn('+最後\n',first['diff'])
        self.assertNotIn('中',first['diff'])
        self.assertEqual(second['status'],'added')
        self.assertIn('+新規\n',second['diff'])
        self.assertTrue(reviewed['read_only'])
        self.assertFalse(reviewed['verification_granted'])
        self.assertEqual(self.ws.syntax_revision,-1)
        self.assertEqual(self.ws.tests_revision,-1)
        self.assertEqual(self.ws.revision,revision)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        with self.assertRaises(ValueError):self.ws.execute('review_changes',{'path':'../secret'})

    def test_external_change_missing_and_corrupted_backup_are_not_attributed_to_agent(self):
        self.edit('changed.txt',b'old','agent')
        self.edit('missing.txt',b'old','agent')
        self.edit('bad.txt',b'old','agent')
        (self.root/'changed.txt').write_text('external')
        (self.root/'missing.txt').unlink()
        change=self.ws.changes[str(self.root/'bad.txt')]
        (self.root/change['backup']).write_text('corrupted')
        rows=self.ws.execute('review_changes',{})['changes']
        self.assertEqual([r['status'] for r in rows],['external_change','missing','backup_invalid'])
        self.assertTrue(all(r['diff'] is None for r in rows))

    def test_no_changes_restoration_and_encoding_details(self):
        self.assertEqual(self.ws.execute('review_changes',{})['changes'],[])
        self.edit('restored.txt',b'original\n','temporary')
        self.ws.write('restored.txt','original\n')
        self.edit('format.txt',b'\xef\xbb\xbfline\r\n','line')
        rows=self.ws.execute('review_changes',{})['changes']
        self.assertEqual(rows[0]['status'],'unchanged')
        self.assertEqual(rows[0]['diff'],'')
        self.assertEqual(rows[1]['status'],'modified')
        self.assertTrue(rows[1]['text_format']['before_utf8_bom'])
        self.assertFalse(rows[1]['text_format']['after_ends_with_newline'])

    def test_output_budgets_and_untrusted_backup_path(self):
        for index in range(4):self.ws.write(str(index)+'.txt','x'*5000)
        with patch('breaktail_agent_diff.MAX_PATCH_CHARS',100),patch('breaktail_agent_diff.MAX_FILES',2):
            reviewed=self.ws.execute('review_changes',{})
        self.assertEqual(reviewed['files_omitted'],2)
        self.assertTrue(reviewed['output_limited'])
        self.assertLessEqual(sum(len(r['diff'] or '') for r in reviewed['changes']),100)
        self.edit('bad.txt',b'old','new')
        self.ws.changes[str(self.root/'bad.txt')]['backup']='../outside'
        self.assertEqual(self.ws.execute('review_changes',{})['changes'][-1]['status'],'backup_invalid')
        self.ws.write('lines.txt','\n'*2001)
        row=self.ws.execute('review_changes',{})['changes'][-1]
        self.assertEqual(row['diff_unavailable'],'line_count_limit')


if __name__=='__main__':unittest.main()
