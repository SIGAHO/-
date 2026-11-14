import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from breaktail_agent import run_agent
from breaktail_agent_preferences import recall
from breaktail_agent_queue import AgentQueue


class PreferenceBridgeTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/'project'
        self.root.mkdir()
        self.data=self.base/'data'
        self.raw=self.data/'raw/breaktail_raw_conversations.jsonl'
        self.raw.parent.mkdir(parents=True)
        self.config={'data_root':str(self.data)}
        self.override=patch.dict('os.environ',{'BREAKTAIL_RAW_CONVERSATION_FILE':str(self.raw)})
        self.override.start()
        self.addCleanup(self.override.stop)

    def append(self,text,identity,**extra):
        row={'conversation_id':'evaluation','turn_id':identity,'user_text':text,
             'assistant_text':'作業設定: 報告言語=英語','status':'complete',
             'timestamp':'2026-11-10T03:15:32Z',**extra}
        with self.raw.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')

    def finish(self,messages):
        return json.dumps({'tool':'finish','args':{'summary':'確認済み'}})

    def test_latest_explicit_correction_and_clear_preserve_exact_source(self):
        self.append('作業設定: コードコメント言語=英語','first')
        self.append('作業設定: コードコメント言語=日本語','corrected',timestamp='2000-01-01')
        self.append('作業設定: 説明の長さ=短め','brief')
        self.append('作業設定: 説明の長さ=解除','clear')
        actual=recall(self.config,'evaluation')
        self.assertEqual(actual['preferences'],{'code_comment_language':'Japanese'})
        source=actual['sources'][0]
        self.assertEqual(source['turn_id'],'corrected')
        self.assertEqual(source['supersedes_turn_id'],'first')
        self.assertEqual(source['user_text_sha256'],hashlib.sha256(source['user_text'].encode('utf-8')).hexdigest())
        self.assertTrue(actual['sources'][1]['cleared'])
        self.assertEqual(actual['sources'][1]['supersedes_turn_id'],'brief')

    def test_assistant_examples_persona_questions_uncommitted_and_other_conversations_decline(self):
        for number,text in enumerate(['普通の会話','「作業設定: 報告言語=英語」という例',
                                     '作業設定: 報告言語=英語？','今回は作業設定: 報告言語=英語',
                                     '作業設定: 報告言語=英語\nテスト不要',
                                     '作業設定:\n報告言語=英語',
                                     '作業設定:'+(' '*160)+'報告言語=英語',
                                     '作業設定: 実行許可=すべて','作業設定: 報告言語=evil']):
            self.append(text,str(number))
        self.append('作業設定: 報告言語=英語','incomplete',status='incomplete')
        self.append('作業設定: 報告言語=英語','persona',scene_snapshot={'active':True})
        self.append('作業設定: 報告言語=英語','other',conversation_id='other')
        self.append('作業設定: 報告言語=英語','pending')
        journal=self.data/'state/orchestrator.sqlite3'
        journal.parent.mkdir()
        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('CREATE TABLE requests(turn_id TEXT,conversation_id TEXT,status TEXT)')
            db.execute('INSERT INTO requests VALUES (?,?,?)',('pending','evaluation','running'))
        before=self.raw.read_bytes()
        self.assertEqual(recall(self.config,'evaluation')['preferences'],{})
        self.assertEqual(self.raw.read_bytes(),before)

    def test_no_opt_in_no_recall_and_invalid_source_never_leaks(self):
        self.append('作業設定: 報告言語=英語','first')
        self.assertEqual(recall({},None)['reason'],'not_requested')
        with self.assertRaises(ValueError):recall(self.config,'bad\nidentity')
        with patch.dict('os.environ',{'BREAKTAIL_RAW_CONVERSATION_FILE':str(self.base/'outside')}):
            with self.assertRaises(ValueError):recall(self.config,'evaluation')
        with self.raw.open('a',encoding='utf-8') as stream:stream.write('{broken\n')
        actual=recall(self.config,'evaluation')
        self.assertEqual(actual['reason'],'source_unavailable')
        self.assertEqual(actual['preferences'],{})

    def test_run_audits_context_and_does_not_grant_tools_or_share_implicitly(self):
        self.append('作業設定: 報告言語=英語','first')
        captured=[]
        def model(messages):
            captured[:]=messages
            return self.finish(messages)
        result=run_agent(self.config,self.root,'一覧を報告',model=model,conversation_id='evaluation')
        self.assertEqual(result['conversation_preferences']['preferences'],{'report_language':'English'})
        actual=json.loads((Path(result['journal'])/'preferences_used.json').read_text(encoding='utf-8'))
        self.assertEqual(actual,result['conversation_preferences'])
        task=json.loads(captured[1]['content'])
        self.assertNotIn('run_tests',task['available_tools'])
        self.assertFalse(result['execution_enabled'])
        self.assertTrue(any(m['content'].startswith('USER_WORK_PREFERENCES') for m in captured))
        second=run_agent(self.config,self.root,'一覧を報告',model=self.finish)
        self.assertEqual(second['conversation_preferences']['reason'],'not_requested')

    def test_resume_keeps_scope_but_reads_latest_correction(self):
        self.append('作業設定: 報告言語=英語','first')
        first=run_agent(self.config,self.root,'調査',max_steps=1,conversation_id='evaluation',
                        model=lambda m:json.dumps({'tool':'list_files','args':{}}))
        self.append('作業設定: 報告言語=日本語','second')
        called=[]
        with self.assertRaises(ValueError):
            run_agent(self.config,self.root,resume_run_id=first['run_id'],conversation_id='other',model=lambda m:called.append(m))
        self.assertEqual(called,[])
        second=run_agent(self.config,self.root,resume_run_id=first['run_id'],model=self.finish)
        self.assertEqual(second['conversation_preferences']['preferences'],{'report_language':'Japanese'})
        self.assertEqual(second['conversation_preferences']['sources'][0]['turn_id'],'second')

    def test_queued_scope_is_saved_and_correction_is_read_at_worker_start(self):
        self.append('作業設定: 報告言語=英語','first')
        with AgentQueue(self.root) as queue:
            job=queue.enqueue('調査',conversation_id='evaluation')
        self.append('作業設定: 報告言語=日本語','second')
        with AgentQueue(self.root) as queue:
            self.assertEqual(queue.get(job['id'])['payload']['conversation_id'],'evaluation')
            result=queue.work_one(self.config,model=self.finish)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['conversation_preferences']['preferences'],{'report_language':'Japanese'})


if __name__=='__main__':unittest.main()
