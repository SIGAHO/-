import json
import io
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from breaktail_agent import Workspace,run_agent,validate_tool_args,TOOL_ARGUMENTS,SCHEMA,model_call


class AgentTests(unittest.TestCase):
    def test_repeated_model_failure_saves_incomplete_result_and_finite_attempts(self):
        for error in (TimeoutError('timeout'),RuntimeError('offline'),OSError('transport')):
            with self.subTest(error=type(error).__name__):
                calls=[]
                def failed(messages):
                    calls.append(messages)
                    raise error
                result=run_agent({},self.root,'cart.pyを調査',max_steps=12,model=failed)
                self.assertEqual(result['status'],'model_failed')
                self.assertEqual(result['steps'],3)
                self.assertEqual(len(calls),3)
                saved=json.loads((Path(result['journal'])/'result.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['model_failures'],3)
                self.assertEqual(saved['last_model_error']['stage'],'model')
                self.assertFalse(saved['tests_passed'])

    def test_failure_after_write_preserves_backup_and_memory_recall(self):
        from breaktail_agent_memory import recall
        (self.root/'cart.py').write_text('x=1',encoding='utf-8')
        actions=iter([
            {'tool':'read_file','args':{'path':'cart.py'}},
            {'tool':'write_file','args':{'path':'cart.py','content':'x=2'}}])
        def model(messages):
            try:return json.dumps(next(actions))
            except StopIteration:raise RuntimeError('model stopped')
        result=run_agent({},self.root,'cart.pyを修正',model=model,max_steps=12)
        self.assertEqual(result['status'],'model_failed')
        self.assertFalse(result['syntax_verified'])
        self.assertEqual((self.root/'cart.py').read_text(),'x=2')
        self.assertEqual((self.root/result['changes'][0]['backup']).read_text(),'x=1')
        memories=recall(Workspace(self.root),'cart.pyを修正')
        self.assertEqual(memories[0]['previous_status'],'model_failed')
        self.assertIn({'step':5,'error':'RuntimeError'},memories[0]['previous_failures'])

    def test_transient_model_failure_can_recover_and_is_still_reported(self):
        count=0
        def model(messages):
            nonlocal count
            count+=1
            if count==1:raise TimeoutError('one failure')
            return json.dumps({'tool':'finish','args':{'summary':'変更なしで終了'}})
        result=run_agent({},self.root,'調査',model=model)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['model_failures'],1)
        self.assertEqual(result['last_model_error']['error'],'TimeoutError')

    def test_model_response_shape_and_truncation_are_rejected(self):
        for body in ([],{'message':None},{'message':{'content':3}},
                     {'message':{'content':''}},{'done_reason':'length','message':{'content':'partial'}}):
            with self.subTest(body=body),patch('breaktail_agent.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(ValueError):
                    model_call({'model':'test','ollama_url':'http://127.0.0.1:1/api/chat'},[])

    def test_tool_contract_rejects_invalid_arguments_before_side_effects(self):
        for tool,args in (
            ('unknown',{}), ('list_files',{'extra':'ignored before fix'}),
            ('read_file',{}), ('write_file',{'path':'bad.txt','content':'x','extra':True}),
            ('write_file',{'path':'bad.txt','content':12}),
            ('replace_text',{'path':'bad.txt','old':None,'new':'x'}),
            ('check_python',{'path':'.'}), ('run_tests',{'timeout':1}),
            ('finish',{'summary':'   '}), ('finish',{'summary':'done','pretend_tests_passed':True}),
            ([],{}), ('list_files',[])):
            with self.subTest(tool=tool,args=args),self.assertRaises(ValueError):
                validate_tool_args(tool,args)
        with self.assertRaises(ValueError):
            self.ws.execute('write_file',{'path':'bad.txt','content':'x','extra':True})
        self.assertFalse((self.root/'bad.txt').exists())
        self.assertEqual(self.ws.changes,{})

    def test_registry_excludes_unpermitted_execution_and_checks_revocation(self):
        self.assertEqual(set(SCHEMA['properties']['tool']['enum']),set(TOOL_ARGUMENTS))
        self.assertNotIn('run_tests',self.ws.available_tools())
        self.assertNotIn('agent.run_tests',self.ws.registry.list_capabilities())
        enabled=Workspace(self.root,allow_execution=True)
        self.assertIn('run_tests',enabled.available_tools())
        enabled.allow_execution=False
        self.assertNotIn('run_tests',enabled.available_tools())
        with self.assertRaises(ValueError):enabled.execute('run_tests',{})

    def test_model_can_recover_from_unknown_and_malformed_tools(self):
        actions=iter([
            {'tool':'fake_shell','args':{'command':'ignored'}},
            {'tool':'write_file','args':{'path':'bad.txt','content':'x','unknown':True}},
            {'tool':'finish','args':{'summary':'','extra':'ignored before fix'}},
            {'tool':'write_file','args':{'path':'good.txt','content':'valid'}},
            {'tool':'finish','args':{'summary':'正しい道具だけで完了。'}}])
        result=run_agent({},self.root,'道具の契約を確認',max_steps=5,
            model=lambda m:json.dumps(next(actions)))
        events=[json.loads(x) for x in (Path(result['journal'])/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len([e for e in events if e.get('error')]),3)
        self.assertFalse((self.root/'bad.txt').exists())
        self.assertEqual((self.root/'good.txt').read_text(),'valid')

    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval'/'agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ws=Workspace(self.root)

    def test_paths_and_protected_files(self):
        for name in ('../outside.py','C:/outside.py','.env','.git/config','.git./config','file.py ','.breaktail-agent/x','code.py:stream'):
            with self.subTest(name=name),self.assertRaises(ValueError):self.ws.path(name)

    def test_ancestor_workspace_cannot_target_breaktail_runtime(self):
        with patch('breaktail_agent.__file__',str(self.root/'installation'/'current'/'breaktail_agent.py')):
            with self.assertRaises(ValueError):self.ws.path('installation/current/breaktail_agent.py')
            with self.assertRaises(ValueError):self.ws.path('installation/data/raw.jsonl')

    def test_read_before_write_and_conflicting_edits(self):
        path=self.root/'a.py';path.write_text('x=1',encoding='utf-8')
        with self.assertRaises(ValueError):self.ws.write('a.py','x=2')
        self.ws.read('a.py');path.write_text('x=3',encoding='utf-8')
        with self.assertRaises(ValueError):self.ws.write('a.py','x=2')
        self.assertEqual(path.read_text(),'x=3')

    def test_replacement_is_unique_and_preserves_backup(self):
        path=self.root/'a.py';path.write_text('x=1\ny=2\n',encoding='utf-8')
        self.ws.read('a.py')
        self.ws.execute('replace_text',{'path':'a.py','old':'x=1','new':'x=4'})
        backup=self.root/self.ws.changes[str(path)]['backup']
        self.assertEqual(backup.read_text(),'x=1\ny=2\n')
        self.assertIn('y=2',path.read_text())
        with self.assertRaises(ValueError):self.ws.execute('replace_text',{'path':'a.py','old':'missing','new':'x'})

    def test_syntax_check_does_not_execute_source(self):
        self.ws.write('main.py',"raise RuntimeError('must not run')")
        self.assertTrue(self.ws.execute('check_python',{})['ok'])
        self.ws.write('main.py','def broken(')
        with self.assertRaises(SyntaxError):self.ws.execute('check_python',{})

    def test_execution_requires_explicit_operator_flag(self):
        with self.assertRaises(ValueError):self.ws.execute('run_tests',{})

    def test_real_test_results_and_empty_suite(self):
        self.ws=Workspace(self.root,allow_execution=True)
        self.assertFalse(self.ws.execute('run_tests',{})['ok'])
        self.ws.write('test_one.py','import unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(2+2,5)\n')
        failure=self.ws.execute('run_tests',{})
        self.assertFalse(failure['ok']);self.assertIn('AssertionError',failure['output'])
        self.ws.write('test_one.py','import unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(2+2,4)\n')
        self.assertTrue(self.ws.execute('run_tests',{})['ok'])

    def test_agent_reads_failure_repairs_and_rechecks(self):
        actions=iter([
            {'tool':'write_file','args':{'path':'a.py','content':'def f(:'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'premature'}},
            {'tool':'write_file','args':{'path':'a.py','content':'def f():\n return 1\n'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'構文を修正して再確認した。'}}])
        messages=[]
        def model(history):
            messages[:]=history
            return json.dumps(next(actions))
        result=run_agent({},self.root,'修正',model=model,max_steps=6)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['steps'],6)
        self.assertTrue(result['syntax_verified'])
        self.assertFalse(result['tests_passed'])
        self.assertTrue(any('SyntaxError' in m['content'] for m in messages))

    def test_finish_needs_checks_after_last_edit(self):
        actions=iter([
            {'tool':'write_file','args':{'path':'a.py','content':'x=1'}},
            {'tool':'finish','args':{'summary':'done'}}])
        result=run_agent({},self.root,'作成',model=lambda m:json.dumps(next(actions)),max_steps=2)
        self.assertEqual(result['status'],'step_limit')
        self.assertFalse(result['syntax_verified'])

    def test_test_execution_flag_requires_passing_tests_for_completion(self):
        actions=iter([
            {'tool':'write_file','args':{'path':'a.py','content':'x=1'}},
            {'tool':'check_python','args':{}},
            {'tool':'finish','args':{'summary':'done'}}])
        result=run_agent({},self.root,'作成',model=lambda m:json.dumps(next(actions)),max_steps=3,allow_execution=True)
        self.assertEqual(result['status'],'step_limit')

    def test_external_changes_cannot_be_reported_verified(self):
        self.ws.write('a.py','x=1')
        (self.root/'a.py').write_text('x=2')
        with self.assertRaises(ValueError):self.ws.verify_readback()

    def test_bad_model_json_is_recoverable_and_no_action_executed(self):
        outputs=iter(['not JSON',json.dumps({'tool':'finish','args':{'summary':'変更なし'}})])
        result=run_agent({},self.root,'調査',model=lambda m:next(outputs),max_steps=2)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['changes'],[])

    def test_cli_dry_run_does_not_create_workspace(self):
        from breaktail_orchestrator import main
        target=self.root/'nonexistent'
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--dry-run','agent','--workspace',str(target),'--text','create files'])
        self.assertEqual(code,0)
        self.assertFalse(target.exists())
        self.assertFalse(json.loads(output.getvalue())['writes_executed'])

    def test_cli_safe_mode_does_not_run_agent(self):
        from breaktail_orchestrator import main
        target=self.root/'nonexistent'
        with redirect_stderr(io.StringIO()):
            code=main(['--safe-mode','agent','--workspace',str(target),'--allow-execution','--text','edit'])
        self.assertEqual(code,1)
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
