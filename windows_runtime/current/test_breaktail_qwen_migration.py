import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import breaktail_v02 as tail
import breaktail_web as web
import breaktail_raw_conversation as raw
import breaktail_structured_memory as structured


class BreaktailQwenMigrationTests(unittest.TestCase):
    def test_old_model_environment_overrides_are_ignored(self):
        with patch.dict(os.environ, {
            "BREAKTAIL_MODEL": "gemma3:12b",
            "BREAKTAIL_EXTRACT_MODEL": "qwen2.5:14b",
        }):
            importlib.reload(tail)
        self.assertEqual(tail.MODEL, "qwen2.5:14b")

    def test_reply_and_extraction_use_the_same_qwen_route(self):
        responses = [
            {"message": {"content": "少し変化があったんだね。"}, "done_reason": "stop"},
            {"message": {"content": json.dumps({
                "scene_change": None, "memory": None, "memory_evidence": None,
            }, ensure_ascii=False)}, "done_reason": "stop"},
        ]
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return io.BytesIO(json.dumps(responses.pop(0), ensure_ascii=False).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(tail.urllib.request, "urlopen", side_effect=fake_urlopen), \
             patch.object(tail, "TURN_LOG_FILE", Path(temp_dir) / "turns.jsonl"):
            reply, complete = tail.generate_reply([], "今日は前より少し楽だった。")
            tail.extract_interpretation("今日は前より少し楽だった。", None)

        self.assertTrue(complete)
        self.assertTrue(reply)
        self.assertEqual([request["model"] for request in requests], ["qwen2.5:14b"] * 2)

    def test_reply_context_excludes_unlinked_legacy_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "memory.jsonl"
            store.write_text("\n".join([
                json.dumps({"id": 1, "content": "ユーザーはEVモーター工場で銅線を曲げる作業をした", "status": "unverified_interpretation"}, ensure_ascii=False),
                json.dumps({"id": 2, "content": "ユーザーは猫と暮らしている", "status": "unverified_interpretation"}, ensure_ascii=False),
            ]), encoding="utf-8")
            with patch.object(tail, "MEMORY_FILE", store), patch.object(tail, "load_profile", return_value=None):
                messages = tail.build_reply_messages([], "EVモーターの工場の作業について話そう", None)
                irrelevant = tail.retrieve_relevant_memories("量子物理の授業について")

        system = messages[0]["content"]
        self.assertNotIn("EVモーター工場", system)
        self.assertNotIn("猫と暮らしている", system)
        self.assertEqual(irrelevant, [])

    def test_japanese_topic_words_retrieve_saved_memory_across_a_new_chat(self):
        memory = "ユーザーは返答が要点と注意点の順で要点的にまとめられることを好む"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "memory.jsonl"
            store.write_text(json.dumps({
                "id": 1,
                "content": memory,
                "status": "unverified_interpretation",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            with patch.object(tail, "MEMORY_FILE", store):
                found = tail.retrieve_relevant_memories("要点の後に続けるのは注意点だったっけ？")

        self.assertEqual(found, [memory])

    def test_state_restore_keeps_visible_messages_and_rebuilds_context_window(self):
        messages = []
        for index in range(6):
            messages.extend([
                {"role": "user", "text": f"user-{index}"},
                {"role": "assistant", "text": f"assistant-{index}", "complete": index != 5},
            ])
        snapshot = {"messages": messages, "scene": {"name": "test"}, "pending": None, "busy": False}
        try:
            web.restore_snapshot(snapshot)
            self.assertEqual(web.STATE["messages"], messages)
            self.assertEqual(web.STATE["scene"], {"name": "test"})
            self.assertEqual(len(web.STATE["history"]), min(len(messages), tail.MAX_HISTORY_MESSAGES))
            self.assertEqual(web.STATE["history"][-1]["content"], "assistant-5\n[応答は途中で切れました]")
        finally:
            web.STATE.update(history=[], messages=[], scene=None, pending=None, busy=False)

    def test_state_restore_refuses_non_loopback_urls(self):
        with self.assertRaises(ValueError):
            web.restore_from_loopback("http://example.com:8765")

    def test_state_restore_preserves_scene_first_pending_memory_ack(self):
        pending = {
            "id": "turn-1",
            "text": "レポートを短くまとめて",
            "memory": {"id": 12, "content": "ユーザーは短い返答を好む"},
            "warning": None,
        }
        snapshot = {
            "messages": [{"role": "user", "text": "レポートを短くまとめて"}],
            "scene": None,
            "pending": pending,
            "busy": False,
        }
        try:
            web.restore_snapshot(snapshot)
            self.assertEqual(web.STATE["pending"], pending)
        finally:
            web.STATE.update(history=[], messages=[], scene=None, pending=None, busy=False)

    def test_scene_context_is_preserved_for_reply_and_extraction(self):
        scene = {"name": "テスト会議", "roles": {"user": "参加者", "assistant": "進行役"}}
        captured = []

        def fake_call(messages, options, timeout, schema=None):
            captured.append(messages)
            return {"message": {"content": json.dumps({
                "scene_change": None, "memory": None, "memory_evidence": None,
            }, ensure_ascii=False)}, "done_reason": "stop"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(tail, "MEMORY_FILE", Path(temp_dir) / "memory.jsonl"), \
                 patch.object(tail, "load_profile", return_value=None), \
                 patch.object(tail, "call_ollama", side_effect=fake_call):
                reply_messages = tail.build_reply_messages([], "話を続けよう", scene)
                tail.extract_interpretation("話を続けよう", scene)

        self.assertIn("テスト会議", reply_messages[0]["content"])
        self.assertIn("現在の場面", captured[0][1]["content"])
        self.assertIn("テスト会議", captured[0][1]["content"])

    def test_new_scene_is_extracted_before_current_turn_reply(self):
        events = []
        new_scene = {
            "name": "即興ラジオ",
            "roles": {"user": "司会", "assistant": "ゲスト"},
        }

        def fake_extract(user_text, old_scene, debug=False):
            events.append(("extract", user_text, old_scene))
            return None, new_scene

        def fake_reply(history, user_text, scene, debug=False, correction_grounding_audit=None):
            events.append(("reply", user_text, scene))
            return "始めよう。", True

        with patch.object(tail, "extract_interpretation", side_effect=fake_extract), \
             patch.object(tail, "generate_reply", side_effect=fake_reply):
            result = web.prepare_turn([], "ラジオ番組の場面を始めよう", None)

        self.assertEqual([event[0] for event in events], ["extract", "reply"])
        self.assertIsNone(events[0][2])
        self.assertEqual(events[1][2], new_scene)
        self.assertEqual(result, ("始めよう。", True, None, new_scene, None))

    def test_interpretation_failure_retains_scene_and_still_replies(self):
        old_scene = {"name": "既存の場面"}
        with patch.object(tail, "extract_interpretation", side_effect=RuntimeError("extract unavailable")), \
             patch.object(tail, "generate_reply", return_value=("通常の返答", True)) as generate:
            result = web.prepare_turn([], "続けよう", old_scene)

        generate.assert_called_once_with([], "続けよう", old_scene, False, correction_grounding_audit={})
        self.assertEqual(result[:4], ("通常の返答", True, None, old_scene))
        self.assertIn("extract unavailable", result[4])

    def test_cli_core_turn_interprets_scene_before_final_reply(self):
        events = []
        new_scene = {"name": "即興ラジオ", "user_role": "司会", "assistant_role": "ゲスト"}

        def fake_extract(user_text, old_scene, debug):
            events.append(("extract", user_text, old_scene))
            return None, new_scene

        def fake_reply(history, user_text, scene, debug, correction_grounding_audit=None):
            events.append(("reply", user_text, scene))
            return "始めよう。", True

        with patch.object(tail, "extract_interpretation", side_effect=fake_extract), \
             patch.object(tail, "generate_reply", side_effect=fake_reply):
            result = tail.prepare_turn([], "ラジオ番組の場面を始めよう", None)

        self.assertEqual([event[0] for event in events], ["extract", "reply"])
        self.assertEqual(events[1][2], new_scene)
        self.assertEqual(result, ("始めよう。", True, None, new_scene, None))

    def test_cli_core_turn_retains_scene_if_interpretation_fails(self):
        old_scene = {"name": "既存の場面"}
        with patch.object(tail, "extract_interpretation", side_effect=RuntimeError("extract unavailable")), \
             patch.object(tail, "generate_reply", return_value=("通常の返答", True)) as generate:
            result = tail.prepare_turn([], "続けよう", old_scene)

        generate.assert_called_once_with([], "続けよう", old_scene, False, correction_grounding_audit={})
        self.assertEqual(result[:4], ("通常の返答", True, None, old_scene))
        self.assertIn("extract unavailable", result[4])

    def test_full_turn_trace_links_payload_extraction_retrieval_and_reply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            memory_file = root / "memory.jsonl"
            trace_file = root / "trace.jsonl"
            memory_file.write_text(json.dumps({"id": 9, "content": "ユーザーはカフェで作業を考えている"}, ensure_ascii=False) + "\n", encoding="utf-8")
            responses = [
                {"message": {"content": json.dumps({"subject_resolution": "zero_subject_user", "scene_change": None, "memory": "ユーザーは今日カフェで作業することを考えている", "memory_evidence": "今日はカフェで作業しようかな"}, ensure_ascii=False)}, "done_reason": "stop"},
                {"message": {"content": "いいね、作業が進みそう。"}, "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 8, "total_duration": 99},
            ]

            def fake_call(messages, options, timeout, schema=None, trace=None, call_kind="model"):
                return responses.pop(0)

            with patch.object(tail, "MEMORY_FILE", memory_file), \
                 patch.object(tail, "FULL_TRACE_FILE", trace_file), \
                 patch.object(tail, "TURN_LOG_FILE", root / "turns.jsonl"), \
                 patch.object(tail, "load_profile", return_value=None), \
                 patch.object(tail, "call_ollama", side_effect=fake_call):
                trace = tail.new_trace("stable-turn", "stable-conversation", "test")
                reply, complete, memory, scene, warning = tail.prepare_turn([], "今日はカフェで作業しようかな", None, trace=trace)
                saved = tail.save_memory(memory, trace)

            records = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(reply, "いいね、作業が進みそう。")
        self.assertTrue(complete)
        self.assertIsNone(scene)
        self.assertIsNone(warning)
        self.assertEqual(saved["id"], 10)
        self.assertTrue(all(record["turn_id"] == "stable-turn" for record in records))
        events = {record["event"] for record in records}
        self.assertTrue({"turn_received", "memory_retrieval", "extraction_raw", "extraction_parsed", "extraction_adopted", "reply_result", "memory_save"} <= events)
        retrieval = next(record for record in records if record["event"] == "memory_retrieval")
        self.assertEqual(retrieval["threshold"], 0.12)
        self.assertIn("candidates", retrieval)
        adopted = next(record for record in records if record["event"] == "extraction_adopted")
        self.assertTrue(adopted["memory_accepted"])

    def test_trace_write_failure_warns_without_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_destination = Path(temp_dir)  # opening a directory as a file fails on every platform
            stderr = io.StringIO()
            with patch.object(tail, "FULL_TRACE_FILE", bad_destination), patch("sys.stderr", stderr):
                tail.trace_event({"turn_id": "log-failure", "conversation_id": "c", "run_id": "r", "channel": "test"}, "test")
        self.assertIn("観測トレースの保存に失敗", stderr.getvalue())

    def test_raw_store_is_append_only_idempotent_and_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "raw.jsonl"
            lock = Path(temp_dir) / "raw.lock"
            with patch.object(raw, "RAW_CONVERSATION_FILE", store), patch.object(raw, "RAW_CONVERSATION_LOCK_FILE", lock):
                self.assertTrue(raw.save_turn("c1", "t1", "原文 user 1", "原文 assistant 1", "complete"))
                self.assertFalse(raw.save_turn("c1", "t1", "改変してはいけない", "改変してはいけない", "complete"))
                self.assertTrue(raw.save_turn("c1", "t2", "原文 user 2", "原文 assistant 2", "incomplete"))
                self.assertTrue(raw.save_turn("c2", "t3", "別会話", "別の返答", "complete"))
                self.assertEqual(len(store.read_text(encoding="utf-8").splitlines()), 3)
                self.assertEqual(raw.get_turn("t1")["user_text"], "原文 user 1")
                self.assertEqual(raw.get_turn("t1")["assistant_text"], "原文 assistant 1")
                self.assertEqual([row["turn_id"] for row in raw.get_context("c1", "t2", before=1, after=3)], ["t1", "t2"])
                self.assertEqual(raw.get_context("c1", "t3", before=1, after=1), [])
                self.assertEqual(raw.get_turn("t2")["status"], "incomplete")

    def test_raw_store_failure_warns_without_interrupting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stderr = io.StringIO()
            with patch.object(raw, "RAW_CONVERSATION_FILE", Path(temp_dir)), patch("sys.stderr", stderr):
                self.assertFalse(raw.save_turn("c", "t", "user", "assistant", "complete"))
        self.assertIn("Raw会話の保存に失敗", stderr.getvalue())

    def test_v2_memory_types_and_relative_times(self):
        reference = "2026-10-10T15:42:00+09:00"
        cases = [
            ("今日はいい日だった", "episode", "2026-10-10", "day"),
            ("昨日先生と話した", "episode", "2026-10-09", "day"),
            ("今眠い", "state", "2026-10-10T15:42:00+09:00", "minute"),
            ("明日学校に行く", "plan", "2026-10-11", "day"),
            ("犬が好き", "preference", None, "unknown"),
            ("RTX3060を使っている", "fact", None, "unknown"),
        ]
        for text, memory_type, event_start, precision in cases:
            self.assertEqual(structured.classify_memory(text), memory_type)
            temporal = structured.normalize_time(text, __import__("datetime").datetime.fromisoformat(reference))
            self.assertEqual(temporal["event_start"], event_start)
            self.assertEqual(temporal["time_precision"], precision)

    def test_v2_memory_preserves_low_precision_and_uncertain_plan(self):
        reference = __import__("datetime").datetime.fromisoformat("2026-10-10T15:42:00+09:00")
        summer = structured.normalize_time("去年の夏に時計を作ってた", reference)
        years = structured.normalize_time("数年前にやった", reference)
        self.assertEqual(summer, {"event_start": "2025-summer", "event_end": None, "time_precision": "season", "time_text": "去年の夏"})
        self.assertEqual(years["event_start"], None)
        self.assertEqual(years["time_precision"], "unknown")
        self.assertEqual(structured.classify_memory("たぶん来週行くかも"), "plan")

    def test_v2_save_has_real_turn_link_and_mixed_read_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = root / "memory.jsonl"
            store.write_text(json.dumps({"id": 1, "content": "旧記憶", "created_at": "old", "status": "unverified_interpretation"}, ensure_ascii=False) + "\n", encoding="utf-8")
            trace = {"turn_id": "raw-turn", "conversation_id": "c", "run_id": "r", "channel": "cli"}
            with patch.object(tail, "MEMORY_FILE", store), \
                 patch.object(tail, "FULL_TRACE_FILE", Path(temp_dir) / "trace.jsonl"):
                saved = tail.save_memory("ユーザーは明日学校に行く予定", trace, "明日学校に行く", "2026-10-10T15:42:00+09:00", 0.55)
                found = tail.retrieve_relevant_memories("学校に行く話")
            rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(saved["id"], 2)
        self.assertEqual(saved["source_turn_ids"], ["raw-turn"])
        self.assertEqual(saved["recorded_at"], "2026-10-10T15:42:00+09:00")
        self.assertIn("ユーザーは明日学校に行く予定", found)
        self.assertEqual(rows[0]["content"], "旧記憶")
        self.assertEqual(structured.normalize_for_read(rows[0])["legacy"], True)

    def test_v2_validation_rejects_bad_source_and_schema(self):
        bad = {"schema_version": 2, "id": 1, "content": "x", "memory_type": "fact", "recorded_at": "2026-10-10T00:00:00", "event_start": None, "event_end": None, "time_precision": "unknown", "time_text": None, "source_turn_ids": [], "confidence": 2, "status": "unverified_interpretation"}
        with self.assertRaises(structured.MemoryValidationError):
            structured.normalize_v2(bad)

    def test_v2_save_failure_does_not_mutate_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace = {"turn_id": "t", "conversation_id": "c", "run_id": "r", "channel": "web"}
            with patch.object(tail, "MEMORY_FILE", Path(temp_dir)):
                with self.assertRaises(OSError):
                    tail.save_memory("ユーザーは犬が好き", trace, "犬が好き")


if __name__ == "__main__":
    unittest.main()
