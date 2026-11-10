from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from breaktail_agent import Workspace


class WorkspaceSearchTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.ws=Workspace(self.root)

    def put(self,name,data):
        path=self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data if isinstance(data,bytes) else data.encode('utf-8'))
        return path

    def test_literal_nested_bom_long_quote_and_read_before_edit(self):
        path=self.put('src/lib/example.txt','\ufefffirst\n'+'a'*500+'猫.*'+ 'b'*500+'\n猫だけ\n')
        result=self.ws.execute('search_text',{'query':'猫.*'})
        match=result['matches'][0]
        self.assertEqual(match['line'],2)
        self.assertEqual(match['column'],501)
        self.assertIn('猫.*',match['quote'])
        self.assertTrue(match['quote_truncated'])
        self.assertLessEqual(len(match['quote']),320)
        self.assertFalse(result['scan_limited'])
        self.assertEqual(self.ws.reads,{})
        with self.assertRaises(ValueError):self.ws.write('src/lib/example.txt','changed')
        self.ws.read('src/lib/example.txt')
        self.ws.write('src/lib/example.txt','changed')
        self.assertEqual(path.read_text(),'changed')

    def test_exclusions_and_scope_guard(self):
        for name in ('.env','hidden/.private','node_modules/lib.txt','cert.pem','store.db'):
            self.put(name,'needle')
        self.put('binary.dat',b'needle\x00')
        self.put('legacy.txt',b'needle\xff')
        self.put('big.txt',b'needle'+b'x'*64000)
        self.put('ok.txt','needle')
        result=self.ws.execute('search_text',{'query':'needle'})
        self.assertEqual([m['path'] for m in result['matches']],['ok.txt'])
        self.assertEqual(result['skipped']['binary'],1)
        self.assertEqual(result['skipped']['oversized'],1)
        for scope in ('../outside','.env','node_modules','missing'):
            with self.assertRaises(ValueError):self.ws.execute('search_text',{'query':'needle','path':scope})
        for query in ('','x'*201,'a\nb'):
            with self.assertRaises(ValueError):self.ws.execute('search_text',{'query':query})
        with self.assertRaises(ValueError):self.ws.execute('search_text',{'query':'needle','regex':'yes'})

    def test_bounds_report_incomplete_search(self):
        self.put('many.txt','\n'.join(['hit']*100))
        result=self.ws.execute('search_text',{'query':'hit'})
        self.assertEqual(len(result['matches']),40)
        self.assertEqual(result['limit_reasons'],['matches'])
        with patch('breaktail_agent_search.MAX_ENTRIES',0):
            result=self.ws.execute('search_text',{'query':'absent'})
        self.assertTrue(result['scan_limited'])
        self.assertEqual(result['limit_reasons'],['entries'])
        with patch('breaktail_agent_search.MAX_FILES',0):
            result=self.ws.execute('search_text',{'query':'absent','path':'many.txt'})
        self.assertEqual(result['limit_reasons'],['files'])
        with patch('breaktail_agent_search.MAX_BYTES',10):
            result=self.ws.execute('search_text',{'query':'absent','path':'many.txt'})
        self.assertEqual(result['limit_reasons'],['bytes'])

    def test_junction_cannot_reveal_external_files(self):
        import os
        import subprocess
        if os.name!='nt':self.skipTest('Windows junction test')
        target=self.root.parent/(self.root.name+'-outside')
        target.mkdir()
        self.addCleanup(target.rmdir)
        outside=target/'secret.txt'
        outside.write_text('needle')
        self.addCleanup(outside.unlink)
        link=self.root/'linked'
        completed=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
        self.assertEqual(completed.returncode,0)
        self.addCleanup(link.rmdir)
        result=self.ws.execute('search_text',{'query':'needle'})
        self.assertEqual(result['matches'],[])
        self.assertEqual(result['skipped']['links'],1)
        with self.assertRaises(ValueError):self.ws.execute('search_text',{'query':'needle','path':'linked'})


if __name__=='__main__':unittest.main()
