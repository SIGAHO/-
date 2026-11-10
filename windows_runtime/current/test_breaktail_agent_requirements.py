import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent import Workspace,run_agent
from breaktail_agent_requirements import normalize,verify


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_finish_cannot_claim_missing_artifact_then_repairs(self):
        requirements={'goal':'説明ファイルを作る','checks':[{'kind':'text_contains','path':'result.txt','text':'verified'}]}
        actions=iter([
            {'tool':'finish','args':{'summary':'できたと言い張る'}},
            {'tool':'write_file','args':{'path':'result.txt','content':'verified'}},
            {'tool':'finish','args':{'summary':'作って確認した'}}])
        result=run_agent({},self.root,'説明ファイルを作る',requirements=requirements,
            model=lambda m:json.dumps(next(actions)),max_steps=3)
        self.assertEqual(result['status'],'completed')
        checks=[json.loads(x) for x in (Path(result['journal'])/'acceptance.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertFalse(checks[0]['passed'])
        self.assertTrue(checks[1]['passed'])
        self.assertEqual(result['steps'],3)
        self.assertTrue((Path(result['journal'])/'requirements.json').exists())

    def test_failed_conditions_never_finish_without_repair(self):
        requirements={'goal':'値を変更','checks':[{'kind':'json_equals','path':'settings.json','pointer':'/port','expected':9090}]}
        (self.root/'settings.json').write_text('{"port":8081}',encoding='utf-8')
        result=run_agent({},self.root,'値を変更',requirements=requirements,max_steps=2,
            model=lambda m:json.dumps({'tool':'finish','args':{'summary':'完了'}}))
        self.assertEqual(result['status'],'step_limit')
        self.assertFalse(result['acceptance']['passed'])
        self.assertEqual(json.loads((self.root/'settings.json').read_text())['port'],8081)

    def test_json_pointer_and_types_are_checked(self):
        ws=Workspace(self.root)
        (self.root/'settings.json').write_text('{"a/b":[{"~flag":true}]}',encoding='utf-8')
        check={'goal':'check','checks':[{'kind':'json_equals','path':'settings.json','pointer':'/a~1b/0/~0flag','expected':True}]}
        self.assertTrue(verify(ws,normalize(ws,check))['passed'])
        check['checks'][0]['expected']=1
        self.assertFalse(verify(ws,normalize(ws,check))['passed'])

    def test_unknown_checks_and_escape_paths_are_rejected(self):
        ws=Workspace(self.root)
        for check in ({'kind':'shell','path':'x'},
                      {'kind':'file_exists','path':'../outside'},
                      {'kind':'file_exists','path':'.breaktail-agent/result.json'},
                      {'kind':'file_exists','path':'x','extra':True},
                      {'kind':'json_equals','path':'x','pointer':'not-a-pointer','expected':1}):
            with self.subTest(check=check),self.assertRaises(ValueError):
                normalize(ws,{'goal':'x','checks':[check]})
        with self.assertRaises(ValueError):normalize(ws,{'goal':'x','checks':[]})

    def test_caller_mutation_cannot_weaken_saved_conditions(self):
        requirements={'goal':'write','checks':[{'kind':'text_contains','path':'x.txt','text':'required'}]}
        actions=iter([
            {'tool':'write_file','args':{'path':'x.txt','content':'wrong'}},
            {'tool':'finish','args':{'summary':'完了'}}])
        def model(messages):
            requirements['checks'][0]['text']='wrong'
            return json.dumps(next(actions))
        result=run_agent({},self.root,'write',requirements=requirements,model=model,max_steps=2)
        self.assertEqual(result['status'],'step_limit')
        saved=json.loads((Path(result['journal'])/'requirements.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['checks'][0]['text'],'required')


if __name__=='__main__':unittest.main()
