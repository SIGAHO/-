import json
import tempfile
import os
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import breaktail_web as web


def profile_items():
    return [{"number": number, "label": f"項目{number}", "value": f"値{number}"}
            for number in range(1, 21)]


class WebCommandReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(web.STATE)
        web.STATE.update(history=[], messages=[], scene=None, pending=None, busy=False,
                         conversation_id="phase79-web", style_samples=[], debug=False)

    def tearDown(self):
        web.STATE.clear()
        web.STATE.update(self.previous)

    def test_read_only_cli_commands_are_reachable_through_web(self):
        for command, expected in (
            ("/capabilities", "できる:"),
            ("/scene", "現在の場面: 未設定"),
            ("/teach", "使い方:"),
            ("/export-training", "/export-training 保存する"),
        ):
            reply, scene = web.web_command_reply(command, [], None, "phase79-web", [])
            self.assertIn(expected, reply)
            self.assertIsNone(scene)
        capabilities, _ = web.web_command_reply("/capabilities", [], None, "phase79-web", [])
        self.assertIn("差分確認後の文字列置換と取消", capabilities)
        self.assertIn("会話から自動でファイルを操作する機能はない", capabilities)

    def test_natural_memory_list_reads_canonical_store_without_model(self):
        with patch.object(web, "memories", return_value=[{"id": 7, "content": "確認用の記憶"}]) as read:
            reply, scene = web.web_command_reply("じゃあ今までの記憶すべて一覧", [], None, "phase79-web", [])
        read.assert_called_once_with()
        self.assertIn("解釈記憶 1 件", reply)
        self.assertIn("[7] [未確認の解釈] 確認用の記憶", reply)
        self.assertIsNone(scene)

    def test_read_workspace_uses_agent_path_guard_without_audit_write(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            (root / "example.txt").write_text("observed", encoding="utf-8")
            listing = web.read_workspace(str(root), "list_files", ".")
            reading = web.read_workspace(str(root), "read_file", "example.txt")
            self.assertIn("example.txt", listing["observation"]["entries"])
            self.assertEqual(reading["observation"]["content"], "observed")
            self.assertFalse((root / ".breaktail-agent").exists())
            for tool, path in (("write_file", "example.txt"), ("read_file", "../example.txt")):
                with self.assertRaises(ValueError):
                    web.read_workspace(str(root), tool, path)
            with self.assertRaises(ValueError):
                web.read_workspace(".", "list_files", ".")
            with self.assertRaises(ValueError):
                web.read_workspace(r"\\example.invalid\share", "list_files", ".")
            (root / "large.txt").write_text("x" * 64001, encoding="utf-8")
            with self.assertRaises(ValueError):
                web.read_workspace(str(root), "read_file", "large.txt")
        with self.assertRaises(ValueError):
            web.read_workspace(str(Path(web.__file__).resolve().parent.parent), "list_files", ".")

    def test_web_rejects_nonlocal_host_and_origin(self):
        self.assertTrue(web.local_request_allowed(f"127.0.0.1:{web.PORT}"))
        self.assertTrue(web.local_request_allowed(f"localhost:{web.PORT}", f"http://localhost:{web.PORT}"))
        self.assertFalse(web.local_request_allowed("evil.example:8765"))
        self.assertFalse(web.local_request_allowed(f"127.0.0.1:{web.PORT}", "http://evil.example"))

    def test_workspace_preview_shows_diff_and_syntax_without_writing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "example.py"
            original = b"def greet():\n    return 'hello'\n"
            source.write_bytes(original)
            result = web.preview_workspace_replace(str(root), "example.py", "hello", "goodbye")
            self.assertIn("+    return 'goodbye'", result["diff"])
            self.assertTrue(result["syntax"]["checked"])
            self.assertFalse(result["written"])
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((root / ".breaktail-agent").exists())
            invalid = web.preview_workspace_replace(str(root), "example.py", "return 'hello'", "return (")
            self.assertEqual(invalid["syntax"]["source"], "replacement_candidate_not_written")
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError):
                web.preview_workspace_replace(str(root), "../example.py", "hello", "goodbye")
            (root / "memory.db").write_text("hello", encoding="utf-8")
            with self.assertRaises(ValueError):
                web.preview_workspace_replace(str(root), "memory.db", "hello", "goodbye")

    def test_preview_commit_is_one_time_and_keeps_verified_backup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "example.py"
            original = b"def greet():\n    return 'hello'\n"
            source.write_bytes(original)
            preview = web.prepare_workspace_replace(str(root), "example.py", "hello", "goodbye")
            self.assertFalse(preview["written"])
            self.assertEqual(source.read_bytes(), original)
            saved = web.commit_workspace_replace(preview["preview_id"])
            self.assertTrue(saved["written"])
            self.assertEqual(source.read_text(encoding="utf-8"), "def greet():\n    return 'goodbye'\n")
            self.assertEqual((root / saved["backup"]).read_bytes(), original)
            receipt = (root / ".breaktail-agent" / saved["run_id"] / "web-edit.json").read_text(encoding="utf-8")
            self.assertIn('"status": "applied"', receipt)
            with self.assertRaises(ValueError):
                web.commit_workspace_replace(preview["preview_id"])
            web.PREPARED_EDITS.clear()  # Undo uses the durable receipt, even after restart.
            undone = web.undo_workspace_edit(str(root), saved["run_id"])
            self.assertTrue(undone["undone"])
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError):
                web.undo_workspace_edit(str(root), saved["run_id"])

    def test_commit_refuses_external_change_and_invalid_syntax(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "example.py"
            source.write_text("value = 'old'\n", encoding="utf-8")
            preview = web.prepare_workspace_replace(str(root), "example.py", "old", "new")
            source.write_text("value = 'external'\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                web.commit_workspace_replace(preview["preview_id"])
            self.assertEqual(source.read_text(encoding="utf-8"), "value = 'external'\n")
            invalid = web.prepare_workspace_replace(str(root), "example.py", "'external'", "(")
            self.assertNotIn("preview_id", invalid)
            self.assertEqual(source.read_text(encoding="utf-8"), "value = 'external'\n")

    def test_undo_refuses_user_change_after_save(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "notes.txt"
            source.write_text("old", encoding="utf-8")
            preview = web.prepare_workspace_replace(str(root), "notes.txt", "old", "new")
            saved = web.commit_workspace_replace(preview["preview_id"])
            source.write_text("user edit", encoding="utf-8")
            with self.assertRaises(ValueError):
                web.undo_workspace_edit(str(root), saved["run_id"])
            self.assertEqual(source.read_text(encoding="utf-8"), "user edit")

    def test_expired_preview_and_changed_backup_do_not_overwrite(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "notes.txt"
            source.write_text("old", encoding="utf-8")
            expired = web.prepare_workspace_replace(str(root), "notes.txt", "old", "new")
            web.PREPARED_EDITS[expired["preview_id"]]["expires"] = time.monotonic() - 1
            with self.assertRaises(ValueError):
                web.commit_workspace_replace(expired["preview_id"])
            self.assertEqual(source.read_text(encoding="utf-8"), "old")
            preview = web.prepare_workspace_replace(str(root), "notes.txt", "old", "new")
            saved = web.commit_workspace_replace(preview["preview_id"])
            (root / saved["backup"]).write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                web.undo_workspace_edit(str(root), saved["run_id"])
            self.assertEqual(source.read_text(encoding="utf-8"), "new")

    def test_undo_recovers_committed_file_after_receipt_interruption(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            source = root / "notes.txt"
            source.write_text("old", encoding="utf-8")
            prepared = web.prepare_workspace_replace(str(root), "notes.txt", "old", "new")
            saved = web.commit_workspace_replace(prepared["preview_id"])
            record = root / ".breaktail-agent" / saved["run_id"] / "web-edit.json"
            receipt = json.loads(record.read_text(encoding="utf-8"))
            receipt["status"] = "prepared"
            del receipt["backup"]
            record.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(web.undo_workspace_edit(str(root), saved["run_id"])["undone"])
            self.assertEqual(source.read_text(encoding="utf-8"), "old")

    def test_web_edit_rejects_bom_and_invalid_python_candidate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            (root / "bom.py").write_bytes(b"\xef\xbb\xbfvalue = 1\n")
            with self.assertRaises(ValueError):
                web.prepare_workspace_replace(str(root), "bom.py", "1", "2")
            (root / "broken.py").write_text("value = (\n", encoding="utf-8")
            result = web.prepare_workspace_replace(str(root), "broken.py", "value", "other")
            self.assertNotIn("preview_id", result)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_web_read_rejects_junction(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
            root = Path(temp_dir)
            outside = root.parent / (root.name + "-outside")
            outside.mkdir()
            try:
                link = root / "linked"
                completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
                self.assertEqual(completed.returncode, 0)
                try:
                    with self.assertRaises(ValueError):
                        web.read_workspace(str(root), "list_files", "linked")
                finally:
                    link.rmdir()
            finally:
                outside.rmdir()

    def test_debug_and_style_state_survive_web_snapshot_restore(self):
        samples = [{"user": f"質問 {number}？"} for number in range(6)]
        with web.LOCK:
            web.STATE.update(style_samples=samples, debug=True)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(web, "STATE_FILE", Path(temp_dir) / "state.json"):
            web.save_state_snapshot()
            web.STATE.update(style_samples=[], debug=False)
            web.restore_from_file(web.STATE_FILE)
        self.assertTrue(web.STATE["debug"])
        self.assertEqual(web.STATE["style_samples"], samples)
        reply, _ = web.web_command_reply("/style-report", [], None, "phase79-web", samples)
        self.assertIn("ユーザー発言 6件", reply)

    def test_web_command_is_raw_logged_but_not_added_to_model_history(self):
        handler = object.__new__(web.Handler)
        handler.send = Mock()
        history = [
            {"role": "user", "content": "普通の発言", "turn_id": "normal"},
            {"role": "assistant", "content": "普通の返答", "turn_id": "normal"},
        ]
        with web.LOCK:
            web.STATE["history"] = history
        with patch.object(web.tail, "save_raw_turn", return_value=True) as saved, \
             patch.object(web, "save_state_snapshot"), patch.object(web.tail, "trace_event"):
            web.Handler.reply(handler, {"text": "/capabilities"})
        self.assertTrue(saved.called)
        self.assertEqual(web.STATE["history"], history)
        response = handler.send.call_args.args[1]
        self.assertTrue(response["persistence"]["raw_saved"])

    def test_web_teach_uses_the_last_conversational_raw_turn(self):
        history = [
            {"role": "user", "content": "普通の発言", "turn_id": "normal"},
            {"role": "assistant", "content": "普通の返答", "turn_id": "normal"},
        ]
        with patch.object(web.tail.teacher_store, "add_teach", return_value={"inserted": True, "teacher_id": "t1"}) as add:
            reply, _ = web.web_command_reply("/teach 望んでいた返答", history, None, "phase79-web", [])
        self.assertIn("Teacher Store", reply)
        self.assertEqual(add.call_args.args[1], "normal")
        self.assertEqual(add.call_args.args[2], [history[0]])

    def test_web_profile_commit_uses_the_same_existing_shortcut_as_cli(self):
        with patch.object(web.tail, "extract_recent_profile", return_value=profile_items()), \
             patch.object(web.tail, "save_verified_profile", return_value={"items": profile_items()}) as save:
            reply, scene = web.web_profile_commit_reply("Breaktailのプロフィールを覚えておいて", [], None)
        self.assertIn("読み戻しも確認", reply)
        self.assertIsNone(scene)
        self.assertTrue(save.called)


if __name__ == "__main__":
    unittest.main()

