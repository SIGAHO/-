import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_requirements import normalize,verify
from breaktail_agent_queue import AgentQueue


class FileHashChecksTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def requirements(self,name,data):
        return {'goal':'指定したファイルを維持する','checks':[
            {'kind':'file_sha256','path':name,'sha256':hashlib.sha256(data).hexdigest()}]}

    def test_exact_bytes_include_newlines_bom_and_binary_with_bounded_reads(self):
        path=self.root/'fixture.dat'
        data=b'\xef\xbb\xbfline\r\n\xff\x00'
        path.write_bytes(data)
        ws=Workspace(self.root)
        requirements=normalize(ws,self.requirements(path.name,data))
        self.assertTrue(verify(ws,requirements)['passed'])
        path.write_bytes(data.replace(b'\r\n',b'\n'))
        self.assertFalse(verify(ws,requirements)['passed'])
        path.write_bytes(b'x'*64000)
        self.assertTrue(verify(ws,self.requirements(path.name,path.read_bytes()))['passed'])
        path.write_bytes(b'x'*64001)
        report=verify(ws,self.requirements(path.name,path.read_bytes()))
        self.assertFalse(report['passed'])
        self.assertEqual(report['checks'][0]['reason'],'ValueError')

    def test_invalid_digest_fields_and_protected_paths_decline(self):
        ws=Workspace(self.root)
        for value in (None,123,[],{},'','a'*63,'A'*64,'g'*64):
            check={'kind':'file_sha256','path':'x.py','sha256':value}
            with self.subTest(value=value),self.assertRaises(ValueError):normalize(ws,{'goal':'x','checks':[check]})
        for name in ('../outside','.breaktail-agent/result.json','.env'):
            with self.subTest(name=name),self.assertRaises(ValueError):normalize(ws,self.requirements(name,b'x'))
        check=self.requirements('x.py',b'x')
        check['checks'][0]['extra']=True
        with self.assertRaises(ValueError):normalize(ws,check)

    def test_weakened_tests_can_pass_but_finish_refuses_then_resume_repairs(self):
        original='import unittest\nfrom calc import total\nclass Tests(unittest.TestCase):\n def test_none(self): self.assertEqual(total(None),0)\n'
        weak='import unittest\nclass Tests(unittest.TestCase):\n def test_pass(self): self.assertTrue(True)\n'
        (self.root/'calc.py').write_text('def total(values):\n return sum(values)\n',encoding='utf-8')
        (self.root/'test_calc.py').write_text(original,encoding='utf-8')
        requirements=self.requirements('test_calc.py',(self.root/'test_calc.py').read_bytes())
        expected=requirements['checks'][0]['sha256']
        actions=iter([
            {'tool':'read_file','args':{'path':'test_calc.py'}},
            {'tool':'write_file','args':{'path':'test_calc.py','content':weak}},
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'弱くしたテストだけで完了を試す'}}])
        def model(messages):
            # Caller-side mutation cannot replace the operator's frozen digest.
            requirements['checks'][0]['sha256']=hashlib.sha256(weak.encode('utf-8')).hexdigest()
            return json.dumps(next(actions))
        first=run_agent({},self.root,'計算実装を修正',requirements=requirements,model=model,max_steps=5,allow_execution=True)
        self.assertEqual(first['status'],'step_limit')
        self.assertTrue(first['tests_passed'])
        self.assertFalse(first['acceptance']['passed'])
        saved=json.loads((Path(first['journal'])/'requirements.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['checks'][0]['sha256'],expected)
        # Restore exact original bytes through the text tool (original uses CRLF on Windows).
        restored=(self.root/first['changes'][0]['backup']).read_bytes().decode('utf-8')
        actions=iter([
            {'tool':'read_file','args':{'path':'test_calc.py'}},
            {'tool':'write_file','args':{'path':'test_calc.py','content':restored}},
            {'tool':'read_file','args':{'path':'calc.py'}},
            {'tool':'write_file','args':{'path':'calc.py','content':'def total(values):\n return sum(values or [])\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'run_tests','args':{}},
            {'tool':'finish','args':{'summary':'元のテストと修正した実装を検証'}}])
        second=run_agent({},self.root,resume_run_id=first['run_id'],model=lambda m:json.dumps(next(actions)),max_steps=7,allow_execution=True)
        self.assertEqual(second['status'],'completed')
        self.assertTrue(second['tests_passed'])
        self.assertTrue(second['acceptance']['passed'])
        self.assertEqual(second['acceptance']['checks'][0]['actual_sha256'],expected)

    def test_queue_keeps_hash_condition_without_granting_execution(self):
        (self.root/'reference.txt').write_bytes(b'fixed\r\n')
        req=self.requirements('reference.txt',b'fixed\r\n')
        with AgentQueue(self.root) as queue:job=queue.enqueue('参照ファイルを維持',req)
        with AgentQueue(self.root) as queue:
            self.assertEqual(queue.get(job['id'])['payload']['requirements'],req)
            done=queue.work_one({},model=lambda m:json.dumps({'tool':'finish','args':{'summary':'ハッシュ確認'}}))
        self.assertEqual(done['status'],'completed')
        self.assertTrue(done['result']['acceptance']['passed'])
        self.assertFalse(done['result']['execution_enabled'])


if __name__=='__main__':unittest.main()
