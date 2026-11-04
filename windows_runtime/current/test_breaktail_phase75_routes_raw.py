import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import breaktail_raw_conversation as raw
import breaktail_v02 as tail
import breaktail_web as web


class RawAndRouteTests(unittest.TestCase):
    def test_failed_and_aborted_turns_allow_empty_assistant_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "raw.jsonl"
            lock = Path(temp_dir) / "raw.lock"
            with patch.object(raw, "RAW_CONVERSATION_FILE", store), \
                 patch.object(raw, "RAW_CONVERSATION_LOCK_FILE", lock):
                self.assertTrue(raw.save_turn("c1", "failed-1", "質問", "", "failed"))
                self.assertTrue(raw.save_turn("c1", "aborted-1", "質問", "", "aborted"))
                rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["status"] for row in rows], ["failed", "aborted"])
        self.assertEqual([row["assistant_text"] for row in rows], ["", ""])

    def test_conflicting_duplicate_turn_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "raw.jsonl"
            lock = Path(temp_dir) / "raw.lock"
            with patch.object(raw, "RAW_CONVERSATION_FILE", store), \
                 patch.object(raw, "RAW_CONVERSATION_LOCK_FILE", lock):
                self.assertTrue(raw.save_turn("c1", "same", "質問", "回答", "complete"))
                self.assertFalse(raw.save_turn("c1", "same", "別の質問", "別の回答", "complete"))
                rows = store.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)

    def test_restore_snapshot_preserves_conversation_id(self):
        previous = dict(web.STATE)
        try:
            web.restore_snapshot({
                "messages": [], "scene": None, "pending": None, "busy": False,
                "conversation_id": "restored-conversation",
            })
            self.assertEqual(web.STATE["conversation_id"], "restored-conversation")
        finally:
            web.STATE.clear()
            web.STATE.update(previous)

    def test_restore_history_never_begins_with_orphan_assistant(self):
        previous = dict(web.STATE)
        messages = [{"role": "user" if index % 2 == 0 else "assistant", "text": str(index)}
                    for index in range(tail.MAX_HISTORY_MESSAGES + 1)]
        try:
            web.restore_snapshot({
                "messages": messages, "scene": None, "pending": None, "busy": False,
                "conversation_id": "restored-conversation",
            })
            self.assertEqual(web.STATE["history"][0]["role"], "user")
            self.assertLessEqual(len(web.STATE["history"]), tail.MAX_HISTORY_MESSAGES)
        finally:
            web.STATE.clear()
            web.STATE.update(previous)

    def test_cli_records_unexpected_turn_failure_and_continues(self):
        inputs = iter(["質問", "/exit"])
        with patch.object(tail, "read_user_text", side_effect=lambda: next(inputs)), \
             patch.object(tail, "prepare_turn", side_effect=ValueError("unexpected")), \
             patch.object(tail, "save_raw_turn", return_value=True) as save, \
             patch.object(tail, "trace_event"), \
             patch("builtins.print"):
            tail.main()
        self.assertTrue(any(call.args[3] == "failed" for call in save.call_args_list))


if __name__ == "__main__":
    unittest.main()
