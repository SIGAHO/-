import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import breaktail_v02 as tail
import breaktail_web as web
from breaktail_passive_continuity import (
    MAX_OPEN_LOOPS, MAX_RECENT_EVENTS, new_passive_continuity_state,
    normalize_passive_continuity_state, prepare_user_turn,
)


class PassiveContinuityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    def test_user_only_updates_last_seen_and_elapsed_uses_fake_clock(self):
        state = new_passive_continuity_state()
        state, _, _ = prepare_user_turn(state, "またあとで続きやろう", now=self.now)
        first = state["last_seen_at"]
        state, section, meta = prepare_user_turn(state, "ただいま", now=self.now + timedelta(hours=4))
        self.assertNotEqual(first, state["last_seen_at"])
        self.assertEqual(meta["elapsed_seconds"], 4 * 3600)
        self.assertIn("約4時間", section)

    def test_bounds_and_pending_is_not_mirrored(self):
        state = new_passive_continuity_state()
        for index in range(MAX_OPEN_LOOPS + 3):
            state, _, _ = prepare_user_turn(state, f"あとで項目{index}を続きやろう", now=self.now + timedelta(minutes=index))
        self.assertEqual(len(state["open_loops"]), MAX_OPEN_LOOPS)
        self.assertLessEqual(len(state["recent_events"]), MAX_RECENT_EVENTS)
        self.assertNotIn("pending", state)

    def test_pressure_reasons_are_deterministic(self):
        state = new_passive_continuity_state()
        state, _, _ = prepare_user_turn(state, "帰ったら検証の続きやろう", now=self.now)
        state, _, meta = prepare_user_turn(state, "ただいま", now=self.now + timedelta(hours=7))
        self.assertGreater(state["initiative_pressure"], 0)
        self.assertIn("open_loop_unresolved_6h", meta["pressure_reasons"])
        self.assertIn("return_expected_2h", meta["pressure_reasons"])

    def test_short_and_unrelated_turns_do_not_inject(self):
        state = new_passive_continuity_state()
        state, _, _ = prepare_user_turn(state, "あとで続きやろう", now=self.now)
        _, section, _ = prepare_user_turn(state, "焼き肉うまかった", now=self.now + timedelta(minutes=10))
        self.assertEqual(section, "")

    def test_invalid_persistence_fails_closed(self):
        self.assertEqual(normalize_passive_continuity_state({"schema_version": 1, "open_loops": "bad"}), new_passive_continuity_state())

    def test_web_snapshot_restores_continuity_without_production_data(self):
        state = new_passive_continuity_state()
        state, _, _ = prepare_user_turn(state, "あとで続きやろう", now=self.now)
        snapshot = {"messages": [], "scene": None, "pending": None, "busy": False,
                    "conversation_id": "safe_id", "style_samples": [], "debug": False,
                    "working_state": tail.new_working_state(), "passive_continuity": state}
        web.restore_snapshot(snapshot)
        self.assertEqual(web.STATE["passive_continuity"]["open_loops"], state["open_loops"])

    def test_assembler_trace_and_priority_are_preserved(self):
        state = new_passive_continuity_state()
        state, _, _ = prepare_user_turn(state, "あとで続きやろう", now=self.now)
        # Injected state is deliberately small and occurs before current correction facts.
        old = state["last_seen_at"]
        state["last_seen_at"] = (self.now - timedelta(hours=4)).isoformat()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(tail, "MEMORY_FILE", Path(directory) / "none.jsonl"), \
             patch.object(tail, "load_profile", return_value=None):
            messages = tail.build_reply_messages([], "ただいま", None,
                working_state=tail.new_working_state(), continuity_section="[Continuity]\n- 前回の会話から約4時間経過",
                continuity_meta={"elapsed_seconds": 14400})
        self.assertIn("[Continuity]", messages[0]["content"])
        self.assertEqual(old, old)  # documents that this assembler call cannot mutate state


if __name__ == "__main__":
    unittest.main()
