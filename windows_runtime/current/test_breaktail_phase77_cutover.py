import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import breaktail_paths as paths
import breaktail_raw_conversation as raw
import breaktail_structured_memory as structured
import breaktail_teacher_store as teacher_store
import breaktail_v02 as tail
import breaktail_web as web


class Phase77CutoverTests(unittest.TestCase):
    def test_all_production_store_defaults_share_data_root(self):
        root = paths.DATA_ROOT.resolve()
        stores = [
            raw.RAW_CONVERSATION_FILE,
            tail.MEMORY_FILE,
            tail.TURN_LOG_FILE,
            tail.FULL_TRACE_FILE,
            tail.TRAINING_FILE,
            teacher_store.DB_FILE,
        ]
        for store in stores:
            self.assertTrue(store.resolve().is_relative_to(root), store)
        self.assertNotIn("2026-10-03", str(root))
        self.assertNotIn("2026-10-12", str(root))

    def test_legacy_memory_is_labeled_without_mutating_store(self):
        source = {"id": 7, "content": "legacy"}
        normalized = structured.normalize_for_read(source)
        self.assertEqual(normalized["provenance_status"], "legacy_unverified")
        self.assertNotIn("provenance_status", source)

    def test_web_state_round_trip_keeps_conversation_scene_and_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            snapshot = {
                "messages": [
                    {"role": "user", "text": "騎士ごっこを始めよう", "turn_id": "t1"},
                    {"role": "assistant", "text": "始めよう", "complete": True, "turn_id": "t1"},
                ],
                "scene": {"name": "城", "user_role": "騎士", "assistant_role": "案内役"},
                "pending": None,
                "busy": False,
                "conversation_id": "phase77conversation",
            }
            with patch.object(web, "STATE_FILE", state_file):
                web.restore_snapshot(snapshot)
                web.save_state_snapshot()
                web.STATE.update(history=[], messages=[], scene=None, pending=None,
                                 busy=False, conversation_id="different")
                web.restore_from_file(state_file)
            self.assertEqual(web.STATE["conversation_id"], "phase77conversation")
            self.assertEqual(web.STATE["scene"]["name"], "城")
            self.assertEqual(len(web.STATE["history"]), 2)

    def test_raw_failure_skips_memory_teacher_and_returns_status(self):
        handler = object.__new__(web.Handler)
        handler.send = Mock()
        with web.LOCK:
            web.STATE.update(history=[], messages=[], scene=None, pending=None,
                             busy=False, conversation_id="phase77rawfailure")
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(web, "STATE_FILE", Path(temp_dir) / "state.json"), \
             patch.object(web, "prepare_turn", return_value=("reply", True, "memory", None, None)), \
             patch.object(tail, "save_raw_turn", return_value=False), \
             patch.object(tail, "save_memory") as save_memory, \
             patch.object(tail, "trace_event"):
            web.Handler.reply(handler, {"text": "hello"})
        save_memory.assert_not_called()
        response = handler.send.call_args.args[1]
        self.assertFalse(response["persistence"]["raw_saved"])
        self.assertIn("Memory", response["warning"])
        history = [{"role": "user", "content": "hello"},
                   {"role": "assistant", "content": "reply"}]
        self.assertFalse(tail.can_teach_last_turn(history, raw_saved=False))
        self.assertTrue(tail.can_teach_last_turn(history, raw_saved=True))


if __name__ == "__main__":
    unittest.main()
