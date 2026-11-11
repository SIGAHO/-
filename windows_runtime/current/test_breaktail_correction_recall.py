"""Anonymous update cases for explicit correction recall."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import breaktail_memory_hub as hub
from breaktail_correction_ledger import commit, preview
import breaktail_v02 as tail


class CorrectionRecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw.jsonl"
        self.ledger = self.root / "memory" / "breaktail_corrections.jsonl"
        self.rows = []

    def add(self, identity, text, conversation="session-a"):
        row = {"turn_id": identity, "conversation_id": conversation,
               "timestamp": f"2026-11-12T00:{len(self.rows):02d}:00Z",
               "user_text": text, "assistant_text": "了解", "status": "complete"}
        self.rows.append(row)
        self.raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")
        return row

    def link(self, label, old_id, new_id):
        checked = preview(self.raw, label, old_id, new_id)
        return commit(self.raw, self.ledger, label, old_id, new_id,
                      checked["old"]["sha256"], checked["new"]["sha256"])

    def test_exact_latest_source_overrides_wrong_draft_without_certifying_fact(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。東支店ではない。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の窓口は今どっち？"
        prompt, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertEqual(meta["correction"]["new_turn_id"], "turn-new-0002")
        self.assertEqual(meta["source_turn_ids"], ["turn-new-0002"])
        self.assertNotIn('"user_text": "望遠鏡修理の窓口は東支店。"', prompt)
        reply, proof = hub.ground_correction_answer(query, "東支店です。", meta)
        self.assertIn("その後", reply)
        self.assertIn("西支店", reply)
        self.assertFalse(proof["external_verification"])
        self.assertEqual(proof["new_turn_id"], "turn-new-0002")
        self.assertEqual(hub.ground_correction_answer(query, "draft", {"correction": meta["correction"],
                                                                      "sources": []}), ("draft", None))

    def test_unlinked_later_change_or_tampered_source_declines(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の窓口は今どっち？"
        self.add("turn-later-003", "訂正：望遠鏡修理の窓口は現在まだ不明。")
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertIsNone(meta["correction"])
        self.assertTrue(meta["correction_unresolved"])
        reply, proof = hub.ground_correction_answer(query, "東支店だよ。", meta)
        self.assertIn("断定できない", reply)
        self.assertEqual(proof["kind"], "correction_source_abstention")
        self.rows.pop()
        self.rows[1]["user_text"] = "望遠鏡修理の窓口は別の場所。"
        self.raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertIsNone(meta["correction"])
        self.assertTrue(meta["correction_unresolved"])

    def test_chained_updates_select_only_the_last_link(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-mid-0002", "望遠鏡修理の窓口は西支店。")
        self.add("turn-new-0003", "望遠鏡修理の窓口は北支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-mid-0002")
        self.link("望遠鏡修理の窓口", "turn-mid-0002", "turn-new-0003")
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertEqual(meta["correction"]["old_turn_id"], "turn-mid-0002")
        self.assertEqual(meta["correction"]["new_turn_id"], "turn-new-0003")
        reply, proof = hub.ground_correction_answer(query, "東支店だよ。", meta)
        self.assertIn("北支店", reply)
        self.assertEqual(proof["new_turn_id"], "turn-new-0003")

    def test_update_link_does_not_promote_pending_work_to_verified(self):
        self.add("turn-old-0001", "未確認：望遠鏡修理の在庫")
        self.add("turn-new-0002", "望遠鏡修理の在庫は明日確認する予定。")
        self.link("望遠鏡修理の在庫", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の在庫は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        reply, proof = hub.ground_correction_answer(query, "確認済みだよ。", meta)
        self.assertIn("明日確認する予定", reply)
        self.assertNotIn("確認済み", reply)
        self.assertFalse(proof["external_verification"])

    def test_two_matched_topics_and_other_session_decline(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        self.link("修理の窓口", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertIsNone(meta["correction"])
        self.assertTrue(meta["correction_unresolved"])
        _, other = hub.build_hub(self.raw, query, "session-b", correction_path=self.ledger)
        self.assertIsNone(other["correction"])

    def test_question_scope_and_quote_budget_decline(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        for query in ("今日はカレー。", "『望遠鏡修理の窓口は今どっち？』は引用です。",
                      "望遠鏡修理の窓口は今どっち？それとファイルも調べて。"):
            _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
            self.assertIsNone(meta["correction"])
        _, meta = hub.build_hub(self.raw, "望遠鏡修理の窓口は今どっち？", "session-a",
                                correction_path=self.ledger, max_chars=1)
        self.assertIsNone(meta["correction"])
        self.assertTrue(meta["correction_unresolved"])

    def test_limited_raw_scan_abstains_instead_of_guessing_old_value(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        with patch.object(hub, "MAX_ROWS", 1):
            _, meta = hub.build_hub(self.raw, "望遠鏡修理の窓口は今どっち？", "session-a",
                                    correction_path=self.ledger)
        self.assertTrue(meta["scan_limited"])
        self.assertIsNone(meta["correction"])
        self.assertTrue(meta["correction_unresolved"])

    def test_current_turn_is_not_recalled_as_fact(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger,
                                current_turn_id="turn-new-0002")
        self.assertIsNone(meta["correction"])

    def test_roleplay_source_is_not_recalled_as_fact(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "ロールプレイで望遠鏡修理の窓口は西支店。")
        with self.assertRaisesRegex(ValueError, "出典にできません"):
            preview(self.raw, "望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        self.assertFalse(self.ledger.exists())
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertIsNone(meta["correction"])

    def test_corrupt_raw_abstains_instead_of_using_old_interpretation(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        with self.raw.open("a", encoding="utf-8") as stream:
            stream.write("{corrupt}\n")
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, "session-a", correction_path=self.ledger)
        self.assertEqual(meta["reason"], "source_unavailable")
        self.assertTrue(meta["correction_unresolved"])
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "MEMORY_FILE", self.root / "memory.jsonl"), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[
                 {"id": 17, "content": "望遠鏡修理の窓口は東支店。"}]), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama") as model, \
             patch.object(tail, "trace_event"), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply([], query,
                                                   trace={"conversation_id": "session-a", "turn_id": "current-turn"})
        self.assertTrue(complete)
        model.assert_not_called()
        self.assertIn("断定できない", reply)

    def test_missing_conversation_identity_abstains_when_corrections_exist(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        query = "望遠鏡修理の窓口は今どっち？"
        _, meta = hub.build_hub(self.raw, query, None, correction_path=self.ledger)
        self.assertEqual(meta["reason"], "no_conversation_identity")
        self.assertTrue(meta["correction_unresolved"])
        reply, proof = hub.ground_correction_answer(query, "西支店だよ。", meta)
        self.assertIn("断定できない", reply)
        self.assertEqual(proof["kind"], "correction_source_abstention")

    def test_reply_builder_receives_only_verified_update(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        audit = {}
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[]):
            messages = tail.build_reply_messages([], "望遠鏡修理の窓口は今どっち？", None,
                                                 trace={"conversation_id": "session-a", "turn_id": "current-turn"},
                                                 hub_audit=audit)
        self.assertIn("西支店", messages[0]["content"])
        self.assertEqual(audit["correction"]["new_turn_id"], "turn-new-0002")

    def test_old_interpretation_is_excluded_before_prompt_and_reason_is_logged(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        old_memory = {"id": 17, "content": "望遠鏡修理の窓口は東支店。",
                      "source_turn_ids": ["turn-old-0001"]}
        unlinked_memory = {"id": 18, "content": "望遠鏡修理の窓口は東支店。"}
        unrelated_memory = {"id": 19, "content": "別の展示会の営業時間。",
                            "source_turn_ids": ["other-turn-0009"]}
        new_memory = {"id": 20, "content": "望遠鏡修理の窓口は西支店。",
                      "source_turn_ids": ["turn-new-0002"]}
        audit = {}
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[old_memory, unlinked_memory, unrelated_memory, new_memory]), \
             patch.object(tail, "gate_memories") as gate, \
             patch.object(tail, "trace_event") as trace_log:
            messages = tail.build_reply_messages([], "望遠鏡修理の窓口は今どっち？", None,
                                                 trace={"conversation_id": "session-a", "turn_id": "current-turn"},
                                                 hub_audit=audit)
        gate.assert_not_called()
        self.assertNotIn("Saved memory candidate", messages[0]["content"])
        self.assertEqual(audit["correction"]["new_turn_id"], "turn-new-0002")
        decisions = [call.kwargs["decisions"] for call in trace_log.call_args_list
                     if len(call.args) > 1 and call.args[1] == "memory_gate"]
        self.assertEqual([item["memory_id"] for item in decisions[0]], [17, 18, 19, 20])
        self.assertEqual([item["reasons"][0] for item in decisions[0]],
                         ["superseded_by_explicit_correction", "source_unknown_during_correction",
                          "narrow_correction_answer_no_memory_needed",
                          "redundant_with_explicit_correction_source"])

    def test_full_reply_path_uses_verified_source_without_model(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "MEMORY_FILE", self.root / "memory.jsonl"), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[]), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama") as model, \
             patch.object(tail, "trace_event"), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply([], "望遠鏡修理の窓口は今どっち？",
                                                   trace={"conversation_id": "session-a", "turn_id": "current-turn"})
        self.assertTrue(complete)
        model.assert_not_called()
        self.assertIn("西支店", reply)
        self.assertIn("外部で確認した事実ではない", reply)

    def test_verified_source_survives_small_model_context_budget(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "MEMORY_FILE", self.root / "memory.jsonl"), \
             patch.object(tail, "NUM_CTX", 4096), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[]), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama") as model, \
             patch.object(tail, "trace_event"), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply([], "望遠鏡修理の窓口は今どっち？",
                                                   trace={"conversation_id": "session-a", "turn_id": "current-turn"})
        self.assertTrue(complete)
        model.assert_not_called()
        self.assertIn("西支店", reply)
        self.assertNotIn("断定できない", reply)

    def test_full_reply_path_abstains_when_recorded_source_changes(self):
        self.add("turn-old-0001", "望遠鏡修理の窓口は東支店。")
        self.add("turn-new-0002", "望遠鏡修理の窓口は西支店。")
        self.link("望遠鏡修理の窓口", "turn-old-0001", "turn-new-0002")
        self.rows[1]["user_text"] = "望遠鏡修理の窓口は北支店。"
        self.raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")
        with patch.object(tail.raw_conversation, "RAW_CONVERSATION_FILE", self.raw), \
             patch.object(tail, "DATA_ROOT", self.root), \
             patch.object(tail, "MEMORY_FILE", self.root / "memory.jsonl"), \
             patch.object(tail, "retrieve_memory_candidates", return_value=[]), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama") as model, \
             patch.object(tail, "trace_event"), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply([], "望遠鏡修理の窓口は今どっち？",
                                                   trace={"conversation_id": "session-a", "turn_id": "current-turn"})
        self.assertTrue(complete)
        model.assert_not_called()
        self.assertIn("断定できない", reply)
        self.assertNotIn("東支店だよ", reply)


if __name__ == "__main__":
    unittest.main()

