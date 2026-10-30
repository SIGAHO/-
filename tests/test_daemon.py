"""Engineering contracts only; fake text is not conversation-quality ground truth."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from companion_core.core import CompanionCore
from companion_core.event_store import EventStore
from companion_core.daemon import CompanionDaemon, DaemonClient, LocalSession, connect_session, endpoint_path
from companion_core.model_adapter import FakeModelAdapter, ModelError
from companion_core.models import Event, SourceType
from companion_core.runtime import OSRuntimeObserver


class Observer:
    def __init__(self):
        self.sample = {"current_time": "2026-10-22T23:00:00+09:00", "uptime": 100,
                       "active_processes": {"editor.exe": 1}}

    def observe(self):
        return dict(self.sample)


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.observer = Observer()

    def daemon(self, start=True, adapter=None):
        d = CompanionDaemon(adapter or FakeModelAdapter(), self.path, self.observer, 0.05)
        self.addCleanup(d.close)
        if start:
            d.start()
        return d

    def test_initial_runtime_event(self):
        d = self.daemon()
        self.assertEqual(d.session.core.events.events[0].source, SourceType.RUNTIME)
        self.assertEqual(DaemonClient(self.path).status()["last_pc_observation"], self.observer.sample)

    def test_clock_uptime_progress_suppressed(self):
        d = self.daemon()
        before = self.path.read_bytes()
        self.observer.sample.update(current_time="2026-10-22T23:00:30+09:00", uptime=130)
        self.assertFalse(d.poll())
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(d.session.status()["last_pc_observation"]["uptime"], 130)

    def test_process_diff_logged_once(self):
        d = self.daemon()
        self.observer.sample["active_processes"] = {"editor.exe": 2}
        self.assertTrue(d.poll())
        self.assertFalse(d.poll())
        self.assertEqual(len(d.session.core.events.events), 2)

    def test_foreground_diff_and_reboot(self):
        d = self.daemon()
        self.observer.sample["foreground_window_title"] = "Example"
        self.assertTrue(d.poll())
        self.observer.sample["uptime"] = 1
        self.assertTrue(d.poll())

    def test_chat_connect_and_cpu_context(self):
        d = self.daemon()
        client = connect_session(FakeModelAdapter(), self.path)
        self.assertIsInstance(client, DaemonClient)
        client.turn("あとでやる")
        self.assertEqual(len(client.status()["open_loops"]), 1)
        self.assertIn("editor.exe", d.session.adapter.requests[0][0]["content"])
        self.assertEqual(len(d.session.core.events.events), 3)

    def test_fallback_and_exclusive_local_owner(self):
        local = connect_session(FakeModelAdapter(), self.path)
        self.addCleanup(local.close)
        self.assertIsInstance(local, LocalSession)
        local.turn("あとでやる")
        with self.assertRaises(OSError):
            connect_session(FakeModelAdapter(), self.path)
        with self.assertRaises(OSError):
            CompanionDaemon(FakeModelAdapter(), self.path)
        local.close()
        self.assertEqual(len(self.daemon().session.status()["open_loops"]), 1)

    def test_closed_owner_cannot_write_after_new_owner_acquires_lease(self):
        old = LocalSession(FakeModelAdapter(['了解。']), self.path)
        old.close()
        new = LocalSession(FakeModelAdapter(['了解。']), self.path)
        self.addCleanup(new.close)
        before = self.path.read_bytes() if self.path.exists() else b''
        with self.assertRaises(RuntimeError):
            old.turn('好きな色は青。')
        self.assertEqual(self.path.read_bytes() if self.path.exists() else b'', before)
        self.assertEqual(new.turn('ただいま'), '了解。')

    def test_closed_daemon_cannot_write_after_local_owner_acquires_lease(self):
        old = CompanionDaemon(FakeModelAdapter(['了解。']), self.path, observer=self.observer)
        old.close()
        new = LocalSession(FakeModelAdapter(['了解。']), self.path)
        self.addCleanup(new.close)
        before = self.path.read_bytes() if self.path.exists() else b''
        with self.assertRaises(RuntimeError):
            old.turn('好きな色は青。')
        with self.assertRaises(RuntimeError):
            old.poll()
        self.assertEqual(self.path.read_bytes() if self.path.exists() else b'', before)
        self.assertEqual(new.turn('ただいま'), '了解。')

    def test_second_daemon_refused(self):
        self.daemon()
        before = self.path.read_bytes()
        with self.assertRaises(OSError):
            CompanionDaemon(FakeModelAdapter(), self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_restart_replay_and_suppression(self):
        d = self.daemon()
        client = DaemonClient(self.path)
        client.turn("あとでやる")
        client.turn("赤じゃなくて青", correction_key="favorite.color")
        old = client.status()
        before = self.path.read_bytes()
        memory = [m.text for m in d.session.core.memory.items]
        d.close()
        restarted = self.daemon()
        self.assertEqual(before, self.path.read_bytes())
        now = DaemonClient(self.path).status()
        for key in ("open_loops", "topic", "emotion", "last_pc_observation"):
            self.assertEqual(now[key], old[key])
        self.assertEqual(restarted.session.core.state.active["favorite.color"].value, "青")
        self.assertEqual([m.text for m in restarted.session.core.memory.items], memory)

    def test_source_gate_live_and_replay(self):
        d = self.daemon()
        original = d.session.core.last_runtime
        forged = Event(kind="runtime_observation", payload={**self.observer.sample, "uptime": 999},
                       source=SourceType.ASSISTANT_GENERATED)
        self.assertFalse(d.session.core.accept_runtime(forged))
        d.session.core.events.append(forged)
        d.session.core.record_assistant_output("あなたは医者です")
        d.close()
        core = self.daemon().session.core
        self.assertEqual(core.last_runtime, original)
        self.assertFalse(any(m.source in {SourceType.ASSISTANT_GENERATED, SourceType.VERIFIED_MEMORY}
                             for m in core.memory.items))
        self.assertFalse(any("医者" in str(f.value) for f in core.state.active.values()))

    def test_status_only_requested_fields_no_log_write(self):
        self.daemon()
        before = self.path.read_bytes()
        status = DaemonClient(self.path).status()
        self.assertEqual(set(status), {"current_time", "open_loops", "topic", "emotion", "last_pc_observation", "conversation_alignment"})
        self.assertEqual(status['conversation_alignment'], {})
        self.assertEqual(before, self.path.read_bytes())

    def test_auth_rejected(self):
        self.daemon()
        client = DaemonClient(self.path)
        client.token = "wrong"
        with self.assertRaisesRegex(OSError, "403"):
            client.status()

    def test_failed_model_preserves_user_only(self):
        d = self.daemon()
        with patch.object(d.session.adapter, "generate", side_effect=ModelError("offline")):
            with self.assertRaises(ModelError):
                DaemonClient(self.path).turn("あとでやる")
        self.assertEqual([e.kind for e in d.session.core.events.events], ["runtime_observation", "user_input"])
        self.assertEqual(len(DaemonClient(self.path).status()["open_loops"]), 1)

    def test_poll_continues_during_generation(self):
        d = self.daemon()
        started, release = threading.Event(), threading.Event()
        errors = []

        def generate(messages):
            started.set()
            if not release.wait(5):
                raise ModelError("test timeout")
            return "接続確認"

        def turn():
            try:
                DaemonClient(self.path).turn("こんにちは")
            except Exception as exc:
                errors.append(exc)

        with patch.object(d.session.adapter, "generate", side_effect=generate):
            worker = threading.Thread(target=turn)
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                self.observer.sample["active_processes"] = {"test.exe": 1}
                self.assertTrue(d.poll())
                self.assertEqual(DaemonClient(self.path).status()["last_pc_observation"], self.observer.sample)
            finally:
                release.set()
                worker.join(10)
        self.assertEqual(errors, [])

    def test_multiple_clients_serialized(self):
        d = self.daemon()
        errors = []

        def turn():
            try:
                DaemonClient(self.path).turn("こんにちは")
            except Exception as exc:
                errors.append(exc)

        workers = [threading.Thread(target=turn) for _ in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["kind"] for e in events[1:]], ["user_input", "assistant_output"] * 6)

    def test_bad_interval(self):
        for interval in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                CompanionDaemon(FakeModelAdapter(), self.path, interval=interval)

    def test_os_observer_schema_and_optional_title(self):
        sample = OSRuntimeObserver().observe()
        self.assertEqual(set(sample), {"current_time", "uptime", "active_processes"})
        if os.name == "nt":
            self.assertGreater(sample["uptime"], 0)
            self.assertTrue(sample["active_processes"])
        self.assertIn("current_time", sample)

    def test_stale_endpoint_fallback(self):
        endpoint_path(self.path).write_text('{"port":0,"token":"stale"}', encoding="utf-8")
        local = connect_session(FakeModelAdapter(), self.path)
        self.addCleanup(local.close)
        self.assertIsInstance(local, LocalSession)

    def test_unreachable_live_daemon_cannot_fallback(self):
        self.daemon()
        endpoint_path(self.path).write_text('{"port":0,"token":"stale"}', encoding="utf-8")
        with self.assertRaises(OSError):
            connect_session(FakeModelAdapter(), self.path)

    def test_low_level_stale_writer_fails_without_corruption(self):
        first = EventStore(self.path)
        stale = EventStore(self.path)
        event = Event(kind="user_input", payload={"text": "example"}, source=SourceType.USER_STATEMENT)
        first.append(event)
        before = self.path.read_bytes()
        with self.assertRaises(OSError):
            stale.append(event)
        self.assertEqual(self.path.read_bytes(), before)

    def test_real_process_cli_observation_crash_and_replay(self):
        env = dict(os.environ, BREAKTAIL_OBSERVE_INTERVAL="0.05")
        process = subprocess.Popen([sys.executable, str(ROOT / "daemon.py"), "--fake", "--event-log", str(self.path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            deadline = time.monotonic() + 15
            while not endpoint_path(self.path).exists():
                if process.poll() is not None:
                    self.fail(process.communicate()[1].decode("utf-8"))
                if time.monotonic() > deadline:
                    self.fail("daemon startup timed out")
                time.sleep(0.05)
            result = subprocess.run([sys.executable, str(ROOT / "chat.py"), "--fake", "--event-log", str(self.path)],
                                    input="あとでやる\n/status\n/exit\n", text=True, encoding="utf-8", capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("last_pc_observation", result.stdout)
            self.assertTrue(DaemonClient(self.path).status()["open_loops"])
            other = subprocess.run([sys.executable, str(ROOT / "daemon.py"), "--fake", "--event-log", str(self.path)],
                                   capture_output=True, timeout=15)
            self.assertEqual(other.returncode, 1)
        finally:
            process.kill()
            process.communicate(timeout=10)
        # OS releases the lease on abnormal exit, despite stale discovery/lock files.
        restarted = self.daemon()
        self.assertTrue(DaemonClient(self.path).status()["open_loops"])
        self.assertTrue(restarted.session.core.last_runtime)


if __name__ == "__main__":
    unittest.main()
