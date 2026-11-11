import tempfile
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
            (root / "large.txt").write_text("x" * 64001, encoding="utf-8")
            with self.assertRaises(ValueError):
                web.read_workspace(str(root), "read_file", "large.txt")
        with self.assertRaises(ValueError):
            web.read_workspace(str(Path(web.__file__).resolve().parent.parent), "list_files", ".")

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
