import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from breaktail_agent import run_agent
from breaktail_agent_queue import AgentQueue
from breaktail_web_agent import WebAgentService


class WebAgentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"model": None, "safe_mode": False,
                       "ollama_url": "http://127.0.0.1:11434/api/chat"}

    def wait_status(self, service, job_id):
        for _ in range(100):
            status = service.status(self.root, job_id)
            if status["status"] not in ("queued", "running"):
                return status
            time.sleep(0.03)
        self.fail("Web agent did not settle")

    def test_explicit_job_reports_actual_write_and_disables_execution(self):
        actions = iter([{"tool": "write_file", "args": {"path": "note.txt", "content": "done"}},
                        {"tool": "finish", "args": {"summary": "note created"}}])
        service = WebAgentService(config_loader=lambda: self.config,
                                  model=lambda messages: json.dumps(next(actions)))
        submitted = service.start(self.root, "create a note")
        result = self.wait_status(service, submitted["job_id"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["execution_enabled"])
        self.assertEqual((self.root / "note.txt").read_text(encoding="utf-8"), "done")
        self.assertEqual(result["summary"], "note created")
        self.assertTrue(result["run_id"])
        self.assertTrue(result["events"])
        self.assertEqual(result["events"][0]["path"], "note.txt")
        self.assertTrue(result["events"][0]["observation"]["written"])

    def test_python_edit_review_and_syntax_check_reach_web_status(self):
        actions = iter([{"tool": "write_file", "args": {"path": "sample.py", "content": "value = 1\n"}},
                        {"tool": "review_changes", "args": {}},
                        {"tool": "check_python", "args": {}},
                        {"tool": "finish", "args": {"summary": "checked"}}])
        service = WebAgentService(config_loader=lambda: self.config,
                                  model=lambda messages: json.dumps(next(actions)))
        submitted = service.start(self.root, "create sample.py and check syntax")
        result = self.wait_status(service, submitted["job_id"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["syntax_verified"])
        self.assertFalse(result["execution_enabled"])
        self.assertEqual([event["tool"] for event in result["events"][:3]],
                         ["write_file", "review_changes", "check_python"])
        self.assertEqual((self.root / "sample.py").read_text(encoding="utf-8"), "value = 1\n")

    def test_cancel_running_job_prevents_pending_write(self):
        entered, release = threading.Event(), threading.Event()
        def model(messages):
            entered.set()
            release.wait(timeout=2)
            return json.dumps({"tool": "write_file", "args": {"path": "forbidden.txt", "content": "x"}})
        service = WebAgentService(config_loader=lambda: self.config, model=model)
        submitted = service.start(self.root, "make a note")
        self.assertTrue(entered.wait(timeout=2))
        cancelled = service.cancel(self.root, submitted["job_id"])
        self.assertTrue(cancelled["cancel_requested"])
        release.set()
        result = self.wait_status(service, submitted["job_id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse((self.root / "forbidden.txt").exists())

    def test_second_job_is_rejected_while_first_is_running(self):
        entered, release = threading.Event(), threading.Event()
        def model(messages):
            entered.set()
            release.wait(timeout=2)
            return json.dumps({"tool": "finish", "args": {"summary": "done"}})
        service = WebAgentService(config_loader=lambda: self.config, model=model)
        first = service.start(self.root, "first task")
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(ValueError, "別の作業を処理中"):
            service.start(self.root, "second task")
        release.set()
        self.assertEqual(self.wait_status(service, first["job_id"])["status"], "completed")
        with AgentQueue(self.root) as queue:
            self.assertEqual(len(queue.list()), 1)

    def test_resume_uses_checkpoint_without_repeating_old_write(self):
        first = run_agent(self.config, self.root, "create a note", max_steps=1,
                          model=lambda messages: json.dumps(
                              {"tool": "write_file", "args": {"path": "note.txt", "content": "ready"}}))
        stamp = (self.root / "note.txt").stat().st_mtime_ns
        service = WebAgentService(config_loader=lambda: self.config,
                                  model=lambda messages: json.dumps(
                                      {"tool": "finish", "args": {"summary": "continued"}}))
        submitted = service.resume(self.root, first["run_id"])
        result = self.wait_status(service, submitted["job_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.root / "note.txt").stat().st_mtime_ns, stamp)
        with self.assertRaises(ValueError):
            service.resume(self.root, first["run_id"])

    def test_remote_model_and_safe_mode_are_rejected_before_enqueue(self):
        for config in ({**self.config, "safe_mode": True},
                       {**self.config, "ollama_url": "https://example.invalid/api/chat"}):
            service = WebAgentService(config_loader=lambda config=config: config)
            with self.assertRaises(ValueError):
                service.start(self.root, "task")
        self.assertFalse((self.root / ".breaktail-agent" / "queue.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()

