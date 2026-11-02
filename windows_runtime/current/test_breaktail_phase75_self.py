import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import breaktail_v02 as tail
from breaktail_self import SelfRuntime, build_self_context, ground_self_reply


class SelfIsolationTests(unittest.TestCase):
    def test_default_route_blocks_fake_vision(self):
        result = ground_self_reply(
            "お前、今の画面見えてる？",
            "見えてるよ。青い画面だ。",
            build_self_context(),
        )
        self.assertEqual(result["decision"], "replace")
        self.assertIn("分からない", result["reply"])

    def test_default_route_does_not_claim_avatar_move(self):
        result = ground_self_reply(
            "アバター動かせる？",
            "もう動かしたよ。",
            build_self_context(),
        )
        self.assertEqual(result["decision"], "replace")
        self.assertIn("接続", result["reply"])

    def test_default_route_does_not_promise_later_initiation(self):
        context = build_self_context()
        self.assertFalse(context["capabilities"]["can_initiate_contact_now"])
        result = ground_self_reply(
            "勝手にあとで話しかけて",
            "分かった。夜になったらこっちから連絡するよ。",
            context,
        )
        self.assertEqual(result["decision"], "replace")
        self.assertEqual(result["reason"], "initiative_adapter_unavailable")
        self.assertIn("接続はない", result["reply"])

    def test_current_turn_request_is_not_mistaken_for_later_initiation(self):
        draft = "何があった？"
        result = ground_self_reply("今話しかけていい？", draft, build_self_context())
        self.assertEqual(result["decision"], "use")
        self.assertEqual(result["reply"], draft)

    def test_scene_cannot_turn_roleplay_into_file_fact(self):
        result = ground_self_reply(
            "お前のファイルは無事？",
            "俺のファイルには影響がない。",
            build_self_context(),
            scene={"name": "怪獣ごっこ"},
        )
        self.assertEqual(result["decision"], "replace")
        self.assertIn("分からない", result["reply"])

    def test_profile_cannot_enable_search_capability(self):
        profile = {
            "items": [{"number": index, "label": f"項目{index}",
                       "value": "Web検索できる" if index == 1 else "設定"}
                      for index in range(1, 21)]
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(tail, "load_profile", return_value=profile), \
             patch.object(tail, "MEMORY_FILE", Path(temp_dir) / "missing.jsonl"):
            messages = tail.build_reply_messages([], "最新価格を検索して", None)
        system = messages[0]["content"]
        self.assertIn("Web検索できる", system)
        self.assertIn("検索アダプタ未接続", system)
        self.assertLess(system.index("Web検索できる"), system.rindex("検索アダプタ未接続"))

    def test_runtime_rejects_non_adapter_object(self):
        with self.assertRaises(TypeError):
            build_self_context({"vision_succeeded": True})

    def test_current_clock_question_uses_runtime_fact_not_model_memory(self):
        context = build_self_context()
        context["facts"]["current_datetime_iso"] = "2026-10-17T22:08:00+09:00"
        context["facts"]["timezone_offset"] = "+09:00"
        result = ground_self_reply(
            "じゃあ今日は何月何日何時何分？",
            "時計にはアクセスできないから分からない。",
            context,
        )
        self.assertEqual(result["decision"], "replace")
        self.assertEqual(result["reason"], "runtime_clock")
        self.assertEqual(result["reply"], "今日は2026年10月17日、現在時刻は22時08分（UTC+09:00）だよ。")

    def test_hiragana_current_time_question_uses_runtime_fact(self):
        context = build_self_context()
        context["facts"]["current_datetime_iso"] = "2026-10-17T22:08:00+09:00"
        context["facts"]["timezone_offset"] = "+09:00"
        result = ground_self_reply("いまなんじ", "現在の時刻は確認できないよ。", context)
        self.assertEqual(result["reason"], "runtime_clock")
        self.assertIn("22時08分", result["reply"])

    def test_current_seconds_question_uses_runtime_fact(self):
        context = build_self_context()
        context["facts"]["current_datetime_iso"] = "2026-10-17T22:08:09+09:00"
        context["facts"]["timezone_offset"] = "+09:00"
        result = ground_self_reply("いまなんびょう", "現在の時刻は確認できないよ。", context)
        self.assertEqual(result["reason"], "runtime_clock")
        self.assertIn("22時08分09秒", result["reply"])

    def test_current_year_question_uses_runtime_fact_not_stale_year(self):
        context = build_self_context()
        context["facts"]["current_datetime_iso"] = "2026-10-17T22:08:00+09:00"
        result = ground_self_reply(
            "まあいいや、今年って何年？",
            "2023年だよ。",
            context,
        )
        self.assertEqual(result["decision"], "replace")
        self.assertEqual(result["reason"], "runtime_clock")
        self.assertEqual(result["reply"], "今年は2026年だよ。")

    def test_direct_clock_question_bypasses_14b_with_runtime_context_fact(self):
        context = build_self_context()
        clock = next(item for item in context["runtime_context"]["facts"]
                     if item["key"] == "clock.current_datetime_iso")
        clock["value"] = "2026-10-17T22:08:00+09:00"
        reply = tail.try_deterministic_reply("じゃあ今日は何月何日何時何分？", context, [])
        self.assertEqual(reply, "今日は2026年10月17日、今は22時08分。")

    def test_quoted_clock_phrase_does_not_bypass_14b(self):
        context = build_self_context()
        self.assertIsNone(tail.try_deterministic_reply("『今年って何年？』を英訳して", context, []))


if __name__ == "__main__":
    unittest.main()
