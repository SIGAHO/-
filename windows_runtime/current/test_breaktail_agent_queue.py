import json
from pathlib import Path
import tempfile
import unittest

from breaktail_agent_queue import AgentQueue
from breaktail_file_lock import ExclusiveLock


class QueueTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_queue_persists_and_same_id_is_idempotent(self):
        identity='a'*32
        with AgentQueue(self.root) as queue:
            job=queue.enqueue('hello',identity=identity)
            self.assertEqual(queue.enqueue('hello',identity=identity)['id'],job['id'])
            with self.assertRaises(ValueError):queue.enqueue('different',identity=identity)
        with AgentQueue(self.root) as queue:
            self.assertEqual(queue.get(identity)['status'],'queued')
            self.assertEqual(len(queue.list()),1)
            self.assertNotIn('allow_execution',queue.get(identity)['payload'])

    def test_one_worker_executes_one_and_retains_real_run_link(self):
        with AgentQueue(self.root) as queue:
            first=queue.enqueue('create',{'goal':'create','checks':[{'kind':'text_contains','path':'x.txt','text':'done'}]})
            second=queue.enqueue('later')
            actions=iter([{'tool':'write_file','args':{'path':'x.txt','content':'done'}},
                {'tool':'finish','args':{'summary':'作成を確認'}}])
            result=queue.work_one({},model=lambda m:json.dumps(next(actions)))
            self.assertEqual(result['id'],first['id'])
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['run_id'],result['result']['run_id'])
            self.assertFalse(result['result']['execution_enabled'])
            self.assertEqual(queue.get(second['id'])['status'],'queued')

    def test_duplicate_worker_refuses_before_claim(self):
        with AgentQueue(self.root) as queue:
            job=queue.enqueue('pending')
            with ExclusiveLock(self.root/'.breaktail-agent/queue.worker.lock',timeout=0):
                with self.assertRaises(TimeoutError):queue.work_one({})
            self.assertEqual(queue.get(job['id'])['status'],'queued')
            with self.assertRaises(ValueError):queue.work_one({},max_steps=0)
            self.assertEqual(queue.get(job['id'])['status'],'queued')

    def test_queued_and_running_cancellation_do_not_execute_pending_write(self):
        with AgentQueue(self.root) as queue:
            first=queue.enqueue('skip')
            self.assertEqual(queue.cancel(first['id'])['status'],'cancelled')
            calls=[]
            self.assertIsNone(queue.work_one({},model=lambda m:calls.append(m)))
            self.assertEqual(calls,[])
            second=queue.enqueue('cancel running')
            def model(messages):
                with AgentQueue(self.root) as controller:controller.cancel(second['id'])
                return json.dumps({'tool':'write_file','args':{'path':'forbidden.txt','content':'x'}})
            result=queue.work_one({},model=model)
            self.assertEqual(result['status'],'cancelled')
            self.assertFalse((self.root/'forbidden.txt').exists())

    def test_stale_running_is_interrupted_and_not_replayed(self):
        with AgentQueue(self.root) as queue:
            job=queue.enqueue('uncertain')
            with queue.db:queue.db.execute("UPDATE jobs SET status='running',worker_pid=123 WHERE id=?",(job['id'],))
            calls=[]
            self.assertIsNone(queue.work_one({},model=lambda m:calls.append(m)))
            self.assertEqual(calls,[])
            self.assertEqual(queue.get(job['id'])['status'],'interrupted')


if __name__=='__main__':unittest.main()
