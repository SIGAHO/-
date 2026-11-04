"""Isolated integration/fault-injection tests; never read Production stores."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from test_model_isolation import ModelIsolatedCase
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import breaktail_orchestrator as orch
import breaktail_v02 as tail
import breaktail_raw_conversation as raw
import breaktail_teacher_store as teachers


class ModelHandler(BaseHTTPRequestHandler):
    payloads = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.respond({"models": [{"name": "qwen2.5:14b"}]})

    def respond(self, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.payloads.append(payload)
        schema = payload.get("format", {}).get("properties", {})
        if "scene_change" in schema:
            user = payload["messages"][-1]["content"].split("ユーザーの現在の発言:\n", 1)[-1]
            candidate = "ユーザーは星空観察が好き" if "俺は星空観察が好き" in user else None
            content = json.dumps({"subject_resolution": "explicit_user", "scene_change": None,
                                  "memory": candidate, "memory_evidence": "俺は星空観察が好き" if candidate else None}, ensure_ascii=False)
        elif "decisions" in schema:
            data = json.loads(payload["messages"][-1]["content"])
            content = json.dumps({"decisions": [dict(index=row["index"], usage="current", reason="explicit user source",
                                      **{check: "pass" for check in data["checks"]}) for row in data["candidates"]]})
        else:
            content = "星空観察が好きなんだね。静かな空を見る時間っていいよね。"
        self.respond({"model": "qwen2.5:14b", "message": {"role": "assistant", "content": content},
                      "done": True, "done_reason": "stop"})


class OrchestratorTests(ModelIsolatedCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("raw", "memory", "trace", "teacher", "training", "state", "errors"):
            (self.root / directory).mkdir()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for obj, name, value in (
            (tail, "MEMORY_FILE", self.root / "memory" / "breaktail_memory.jsonl"),
            (tail, "FULL_TRACE_FILE", self.root / "trace" / "breaktail_full_turn_trace.jsonl"),
            (tail, "TURN_LOG_FILE", self.root / "trace" / "breaktail_turns.jsonl"),
            (tail, "TRAINING_FILE", self.root / "training" / "reviewed.jsonl"),
            (raw, "RAW_CONVERSATION_FILE", self.root / "raw" / "raw.jsonl"),
            (raw, "RAW_CONVERSATION_LOCK_FILE", self.root / "raw" / "raw.lock"),
            (teachers, "DB_FILE", self.root / "teacher" / "teacher.sqlite3"),
            (teachers, "MODEL_TRACE_FILE", self.root / "trace" / "breaktail_full_turn_trace.jsonl"),
            (tail, "TURN_LOG_STATUS", {"last_success": None, "last_error": None}),
            (raw, "RAW_CONVERSATION_STATUS", {"last_success": None, "last_error": None}),
        ):
            self.stack.enter_context(patch.object(obj, name, value))
        self.stack.enter_context(patch.object(tail, "load_profile", return_value=None))
        self.config = orch.load_config(data_root=self.root)
        self.config.update(retry_seconds=0.001, poll_seconds=0.01, health_timeout_seconds=0.1)
        self.engine = orch.Orchestrator(self.config, core=tail)
        self.addCleanup(self.close_engine)

    def close_engine(self):
        self.engine.journal.close()
        for handler in list(self.engine.logger.handlers):
            handler.close()
            self.engine.logger.removeHandler(handler)

    def submit(self, text="質問です", cid="conversation", rid=None):
        return self.engine.journal.submit(text, cid, rid)

    def result(self, request):
        return json.loads(self.engine.journal.request(request["id"])["result"])

    def mock_turn(self, *_, working_state=None, **kwargs):
        if working_state is not None:
            working_state["topic"] = "new topic"
        return "回答です", True, "ユーザーは星空観察が好き", None, None

    def test_http_end_to_end_reuses_actual_core_and_memory_gate(self):
        ModelHandler.payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/chat"
        self.config["ollama_url"] = url
        with patch.object(tail, "OLLAMA_URL", url):
            first = self.submit("俺は星空観察が好き", cid="first")
            self.assertEqual(self.engine.process_next()["status"], "done")
            # Another conversation has no history source, so retrieval must pass Gate.
            second = self.submit("俺の星空観察の好みを覚えてる？", cid="second")
            self.assertEqual(self.engine.process_next()["status"], "done")
            health = self.engine.health()
        self.assertEqual(health["status"], "ok")
        self.assertTrue(self.result(first)["raw_saved"])
        memory = json.loads(tail.MEMORY_FILE.read_text(encoding="utf-8").strip())
        self.assertEqual(memory["schema_version"], 2)
        self.assertEqual(memory["source_turn_ids"], [first["turn_id"]])
        events = [json.loads(line) for line in tail.FULL_TRACE_FILE.read_text(encoding="utf-8").splitlines()]
        gate = [e for e in events if e["event"] == "memory_gate" and e["turn_id"] == second["turn_id"]]
        self.assertTrue(any(memory["id"] in event["used_ids"] for event in gate))
        self.assertTrue(any(e["event"] == "self_reply_grounding" for e in events))
        self.assertTrue(any(e["event"] == "phase7_reply_postprocess" for e in events))
        self.assertEqual(len(list(raw.iter_turns())), 2)
        self.assertTrue(all("payload" not in item for item in raw.iter_turns()))
        queue = dict(self.engine.journal.db.execute("SELECT * FROM learning_queue WHERE request_id=?", (first["id"],)).fetchone())
        self.assertNotIn("target_text", queue)
        self.assertIsNone(queue["teacher_id"])
        self.assertEqual(teachers.active_reply_teachers(), [])

    def test_request_replay_never_regenerates_or_duplicates_raw_memory(self):
        row = self.submit(rid="stable-id")
        with patch.object(tail, "prepare_turn", side_effect=self.mock_turn) as generate:
            self.engine.process_next()
            duplicate = self.submit(rid="stable-id")
            self.assertEqual(duplicate["status"], "done")
            self.assertIsNone(self.engine.process_next())
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(len(list(raw.iter_turns())), 1)
        self.assertEqual(len(tail.MEMORY_FILE.read_text(encoding="utf-8").splitlines()), 1)
        with self.assertRaises(ValueError):
            self.submit("different", rid=row["id"])

    def test_crash_after_generated_checkpoint_resumes_without_model_call(self):
        row = self.submit()
        trace = tail.new_trace(row["turn_id"], row["conversation_id"])
        with patch.object(tail, "prepare_turn", side_effect=self.mock_turn):
            result = self.engine._generate(row, trace)
        self.engine.journal.update(row["id"], status="running", attempts=1)
        # Simulate crash after Memory append, before session transaction commit.
        tail.save_raw_turn(trace, row["user_text"], result["reply"], "complete", None)
        tail.save_memory(result["memory"], trace, user_text=row["user_text"])
        self.engine.journal.close()
        self.engine.journal = orch.Journal(self.root)
        with patch.object(tail, "prepare_turn", side_effect=AssertionError("must not regenerate")), \
             patch.object(tail, "save_memory", side_effect=AssertionError("must not append again")):
            self.assertEqual(self.engine.process_next()["status"], "done")
        self.assertEqual(len(list(raw.iter_turns())), 1)
        self.assertEqual(len(tail.MEMORY_FILE.read_text(encoding="utf-8").splitlines()), 1)

    def test_failure_rolls_back_session_retries_and_continues_next_conversation(self):
        row = self.submit()
        with patch.object(tail, "prepare_turn", side_effect=ValueError("injected")):
            self.assertEqual(self.engine.process_next()["status"], "queued")
            self.engine.journal.update(row["id"], available_at=0)
            self.assertEqual(self.engine.process_next()["status"], "failed")
        self.assertEqual(self.engine.journal.session("conversation", tail)["history"], [])
        self.assertEqual(raw.get_turn(row["turn_id"])["status"], "failed")
        self.submit(cid="next")
        with patch.object(tail, "prepare_turn", return_value=("ok", True, None, None, None)):
            self.assertEqual(self.engine.process_next()["status"], "done")

    def test_raw_failure_never_saves_memory_or_commits_session(self):
        row = self.submit()
        with patch.object(tail, "prepare_turn", side_effect=self.mock_turn), \
             patch.object(tail, "save_raw_turn", return_value=False), \
             patch.object(tail, "save_memory") as save:
            self.engine.process_next()
        save.assert_not_called()
        self.assertEqual(self.engine.journal.session("conversation", tail)["history"], [])
        self.assertEqual(self.engine.journal.request(row["id"])["phase"], "generated")

    def test_memory_failure_does_not_drop_reply_and_is_evaluated(self):
        row = self.submit()
        with patch.object(tail, "prepare_turn", side_effect=self.mock_turn), \
             patch.object(tail, "save_memory", side_effect=OSError("disk")):
            self.assertEqual(self.engine.process_next()["status"], "done")
        self.assertTrue(self.result(row)["raw_saved"])
        evidence = json.loads(self.engine.journal.db.execute("SELECT evidence FROM evaluations").fetchone()[0])
        self.assertIn("memory_not_verified", evidence["issues"])

    def test_safe_mode_still_logs_and_resumes_but_skips_memory_and_teacher(self):
        self.config["safe_mode"] = True
        row = self.submit()
        with patch.object(tail, "prepare_turn", side_effect=self.mock_turn), patch.object(tail, "save_memory") as save:
            self.assertEqual(self.engine.process_next()["status"], "done")
        save.assert_not_called()
        self.assertTrue(raw.get_turn(row["turn_id"]))
        with self.assertRaises(ValueError):
            self.engine.review(row["id"], "人の訂正", "human")

    def test_interactive_commands_reuse_adapter_and_respect_safe_mode(self):
        self.config["safe_mode"] = True
        with patch.object(tail, "prepare_turn", side_effect=AssertionError("no model calls")), \
             patch.object(tail, "forget_memory") as forget:
            self.assertIn("5往復", self.engine.command("/capabilities", "cli"))
            self.assertIn("safe mode", self.engine.command("/forget 1", "cli"))
            self.assertIn("未設定", self.engine.command("/scene", "cli"))
        forget.assert_not_called()

    def test_per_store_override_cannot_escape_configured_root(self):
        with patch.dict(os.environ, {"BREAKTAIL_MEMORY_FILE": str(self.root.parent / "unrelated-memory.jsonl")}):
            with self.assertRaises(ValueError):
                orch.load_core(self.config)

    def test_history_window_is_recovered_from_raw_and_is_conversation_scoped(self):
        self.config["history_turns"] = 2
        with patch.object(tail, "prepare_turn", return_value=("response", True, None, None, None)) as generate:
            for index in range(4):
                self.submit(f"message-{index}")
                self.engine.process_next()
            self.assertEqual(len(generate.call_args.args[0]), 4)
            self.assertEqual(generate.call_args.args[0][0]["content"], "message-1")
            self.submit("別の会話", cid="other")
            self.engine.process_next()
            self.assertEqual(generate.call_args.args[0], [])

    def test_delayed_retry_cannot_be_overtaken_in_same_conversation(self):
        first = self.submit("first")
        self.submit("second")
        self.submit("other", cid="other")
        self.engine.journal.update(first["id"], available_at=10**12)
        with patch.object(tail, "prepare_turn", return_value=("ok", True, None, None, None)):
            self.assertEqual(self.engine.process_next()["conversation_id"], "other")
            self.assertIsNone(self.engine.process_next())

    def test_generated_targets_rejected_across_turns_and_human_review_exports(self):
        row = self.submit()
        with patch.object(tail, "prepare_turn", return_value=("生成された回答", True, None, None, None)):
            self.engine.process_next()
        raw.save_turn("another", "another-turn", "input", "別の生成文", "complete")
        with self.assertRaises(ValueError):
            self.engine.review(row["id"], " 別の 生成文 ", "reviewer")
        # Shared Teacher Store boundary also protects legacy CLI/Web/export.
        with self.assertRaises(teachers.TeacherStoreError):
            teachers.add_teach("conversation", row["turn_id"], [{"role": "user", "content": "質問"}], "別の生成文")
        reviewed = self.engine.review(row["id"], "人が独立に書いた正解例です。", "reviewer")
        self.assertTrue(reviewed["inserted"])
        self.assertEqual(teachers.export_training(tail.TRAINING_FILE), 1)
        messages = json.loads(tail.TRAINING_FILE.read_text(encoding="utf-8"))["messages"]
        self.assertEqual(messages[-1]["content"], "人が独立に書いた正解例です。")
        raw.save_turn("later", "later-turn", "input", "人が独立に書いた正解例です。", "complete")
        self.assertEqual(teachers.export_training(tail.TRAINING_FILE), 0)

    def test_continuity_update_reaches_caller_checkpoint(self):
        continuity = tail.new_passive_continuity_state()
        with patch.object(tail, "try_deterministic_reply", return_value="ok"):
            tail.prepare_turn([], "あとで検証の続きやろう", None, passive_continuity=continuity)
        self.assertIsNotNone(continuity["last_seen_at"])
        self.assertTrue(continuity["open_loops"])

    def test_recall_question_cannot_manufacture_new_preference_evidence(self):
        response = {"message": {"content": json.dumps({"subject_resolution": "explicit_user", "scene_change": None,
                   "memory": "ユーザーは星空観察が好き", "memory_evidence": "俺の星空観察の好み"}, ensure_ascii=False)}}
        with patch.object(tail, "call_ollama", return_value=response):
            memory, _ = tail.extract_interpretation("俺の星空観察の好みを覚えてる？", None)
        self.assertIsNone(memory)
        response["message"]["content"] = json.dumps({"subject_resolution": "explicit_user", "scene_change": None,
                    "memory": "ユーザーは星空観察が好き", "memory_evidence": "俺は星空観察が好き"}, ensure_ascii=False)
        with patch.object(tail, "call_ollama", return_value=response):
            memory, _ = tail.extract_interpretation("俺は星空観察が好き。覚えてる？", None)
        self.assertIsNotNone(memory)

    def test_lock_is_released_when_process_dies(self):
        path = self.root / "crash.lock"
        code = ("import sys,time; from breaktail_orchestrator import ExclusiveLock; "
                "guard=ExclusiveLock(sys.argv[1]); guard.__enter__(); print('locked',flush=True); time.sleep(30)")
        child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE,
                                 cwd=Path(orch.__file__).parent, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(TimeoutError):
                with orch.ExclusiveLock(path, timeout=0.05):
                    pass
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        with orch.ExclusiveLock(path, timeout=0.05):
            pass

    def test_raw_pid_lock_recovers_after_owning_process_is_killed(self):
        code = ("import sys,time; from pathlib import Path; import breaktail_raw_conversation as raw; "
                "raw.RAW_CONVERSATION_LOCK_FILE=Path(sys.argv[1]); guard=raw._FileLock(); "
                "guard.__enter__(); print('locked',flush=True); time.sleep(30)")
        child = subprocess.Popen([sys.executable, "-c", code, str(raw.RAW_CONVERSATION_LOCK_FILE)],
                                 stdout=subprocess.PIPE, cwd=Path(orch.__file__).parent, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        self.assertTrue(raw.save_turn("recovered", "recovered", "input", "reply", "complete"))

    def test_supervised_child_process_drains_real_persistent_queue(self):
        root = self.root / "subprocess-data"
        env = dict(os.environ, PYTHONUTF8="1")
        script = str(Path(orch.__file__).resolve())
        base = [sys.executable, script, "--data-root", str(root), "--safe-mode"]
        submit = subprocess.run([*base, "submit", "--text", "今何時？", "--request-id", "subprocess"],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(submit.returncode, 0, submit.stderr)
        drain = subprocess.run([*base, "daemon", "--once"], env=env, capture_output=True,
                               text=True, encoding="utf-8", timeout=20)
        self.assertEqual(drain.returncode, 0, drain.stderr)
        journal = orch.Journal(root)
        try:
            row = journal.request("subprocess")
            self.assertEqual(row["status"], "done")
            self.assertTrue(json.loads(row["result"])["raw_saved"])
            self.assertEqual(journal.get_meta("supervisor")["restarts"], 0)
        finally:
            journal.close()

    def test_watchdog_restarts_only_its_owned_child(self):
        first, second = Mock(), Mock()
        first.pid, first.returncode = 123456, None
        first.poll.side_effect = lambda: first.returncode
        def killed():
            first.returncode = -9
        first.kill.side_effect = killed
        second.pid, second.returncode = 123457, 0
        second.poll.return_value = 0
        config = dict(self.config, restart_limit=1, restart_backoff_seconds=0.001)
        prior_get = orch.Journal.get_meta
        def get_meta(journal, key):
            if key == "worker:123456":
                return {"pid": first.pid, "heartbeat": time.time() - 3600}
            return prior_get(journal, key)
        with patch.object(orch.subprocess, "Popen", side_effect=[first, second]) as launch, \
             patch.object(orch.Journal, "get_meta", get_meta):
            self.assertEqual(orch.supervise(config, orch.DEFAULT_CONFIG), 0)
        self.assertEqual(launch.call_count, 2)
        first.kill.assert_called_once()
        second.kill.assert_not_called()
        first.terminate.assert_not_called()
        self.assertEqual(self.engine.journal.get_meta("supervisor")["restarts"], 1)

    def test_operational_log_rotates_without_truncating_evidence(self):
        config = dict(self.config, log_max_bytes=100, log_backups=2)
        other = self.root / "rotate"
        logger = orch.make_logger(other, config)
        try:
            for _ in range(20):
                logger.warning("non-sensitive diagnostic message long enough to rotate")
            self.assertTrue((other / "errors" / "orchestrator.log.1").exists())
        finally:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def test_dry_run_creates_nothing_and_makes_no_model_call(self):
        root = self.root / "does-not-exist"
        with contextlib.redirect_stdout(__import__("io").StringIO()), patch.object(orch, "load_core", side_effect=AssertionError()):
            self.assertEqual(orch.main(["--data-root", str(root), "--dry-run", "chat", "--text", "test"]), 0)
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
