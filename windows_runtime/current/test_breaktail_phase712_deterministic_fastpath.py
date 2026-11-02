import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import breaktail_v02 as tail
from breaktail_deterministic_reply import try_deterministic_reply
from breaktail_runtime_context import build_runtime_context
from breaktail_runtime_facts import FactStore, fact
from breaktail_self import SelfRuntime, build_self_context


NOW = datetime(2031, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=9)))
CAPABILITIES = {
    "vision_state": "not_connected", "can_observe_screen_now": False,
    "can_request_avatar_move_now": False, "can_request_file_operation_now": False,
    "can_request_web_search_now": False, "search_state": "not_attempted",
}


class DeterministicFastPathTests(unittest.TestCase):
    def context(self, text, store=None, **kwargs):
        return build_runtime_context(text, CAPABILITIES, store=store or FactStore(), now=NOW, **kwargs)

    def test_clock_and_weekday_are_code_owned(self):
        self.assertEqual(try_deterministic_reply("今何時？", self.context("今何時？")), "今は3時04分。")
        self.assertEqual(try_deterministic_reply("いまなんじ", self.context("いまなんじ")), "今は3時04分。")
        self.assertEqual(try_deterministic_reply("いまなんびょう", self.context("いまなんびょう")), "今は3時04分00秒。")
        self.assertEqual(try_deterministic_reply("今のタイムゾーンは？", self.context("今のタイムゾーンは？")), "この実行環境の現在のタイムゾーンはUTC+09:00。")
        self.assertIsNone(try_deterministic_reply("タイムゾーンって何？", self.context("タイムゾーンって何？")))
        self.assertEqual(try_deterministic_reply("今日は何曜日？", self.context("今日は何曜日？")), "今日は木曜日。")

    def test_capability_answers_do_not_need_ollama(self):
        self.assertIn("接続されていない", try_deterministic_reply("検索できる？", self.context("検索できる？")))
        self.assertIn("見えない", try_deterministic_reply("画面見える？", self.context("画面見える？")))
        action = try_deterministic_reply("今ネット検索して最新ニュース取って", self.context("今ネット検索して最新ニュース取って"))
        self.assertIn("接続されていない", action)
        self.assertNotIn("検索した", action)
        self.assertIsNone(try_deterministic_reply("ネット検索ってどう動くの？", self.context("ネット検索ってどう動くの？")))

    def test_ram_memory_and_ollama_use_code_facts(self):
        ram = fact("system.memory", {"available_gib": 8.0, "used_percent": 50.0}, "test", observed_at=NOW.isoformat())
        with patch("breaktail_runtime_context.collect_system_memory", return_value=ram):
            self.assertIn("8 GiB", try_deterministic_reply("RAM余ってる？", self.context("RAM余ってる？")))
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "memory.jsonl"
            memory.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
            self.assertEqual(try_deterministic_reply("Memory何件？", self.context("Memory何件？", memory_file=memory)), "Memoryは2件。")
        disconnected = fact("service.ollama", {"reachable": False}, "test", status="not_connected", observed_at=NOW.isoformat())
        with patch("breaktail_runtime_context.collect_local_service", return_value=disconnected):
            self.assertIn("接続できていない", try_deterministic_reply("Ollama生きてる？", self.context("Ollama生きてる？")))
        web_disconnected = fact("service.web", {"reachable": False}, "test", status="not_connected", observed_at=NOW.isoformat())
        with patch("breaktail_runtime_context.collect_local_service", return_value=web_disconnected):
            self.assertIn("接続できていない", try_deterministic_reply("Web server生きてる？", self.context("Web server生きてる？")))

    def test_system_identity_uses_code_fact(self):
        reply = try_deterministic_reply("今のOSは何？", self.context("今のOSは何？"))
        self.assertIn("OSは", reply)
        self.assertIn("Pythonは", reply)

    def test_disk_capacity_uses_code_fact(self):
        reply = try_deterministic_reply("ディスクの空き容量は？", self.context("ディスクの空き容量は？"))
        self.assertIn("空きは", reply)
        self.assertIn("GiB", reply)

    def test_cpu_count_uses_code_fact(self):
        reply = try_deterministic_reply("CPUコア数は？", self.context("CPUコア数は？"))
        self.assertIn("CPU論理コア数は", reply)

    def test_local_dictionary_returns_only_bundled_exact_term(self):
        self.assertEqual(
            try_deterministic_reply("JSONって何？", self.context("JSONって何？")),
            "JSON: キーと値で構造化したデータを表すテキスト形式。",
        )
        self.assertEqual(
            try_deterministic_reply("LoRAって何？", self.context("LoRAって何？")),
            "LoRA: 大きなモデル本体の一部に小さな追加学習行列を重ねる軽量な調整手法。",
        )
        self.assertIsNone(try_deterministic_reply("小説って何？", self.context("小説って何？")))

    def test_history_and_last_error_do_not_invent_zero_or_success(self):
        self.assertEqual(try_deterministic_reply("会話履歴何件？", self.context("会話履歴何件？", history_count=7)), "会話履歴は7件。")
        self.assertEqual(try_deterministic_reply("直近エラーある？", self.context("直近エラーある？")), "直近エラーは確認できていない。")

    def test_verified_operation_only_claims_success(self):
        store = FactStore()
        store.finish_operation("memory.save", executed=True, verified=False, status="failed", verification_source=None, result_summary="unverified")
        self.assertIn("成功したとは言えない", try_deterministic_reply("さっき保存成功した？", self.context("さっき保存成功した？", store)))
        store.finish_operation("memory.save", executed=True, verified=True, status="ok", verification_source="readback", result_summary="verified")
        self.assertIn("検証まで成功", try_deterministic_reply("さっき保存成功した？", self.context("さっき保存成功した？", store)))

    def test_explicit_math_and_date_results(self):
        self.assertEqual(try_deterministic_reply("8秒と5秒の差は？", self.context("8秒と5秒の差は？")), "差は3秒。")
        self.assertEqual(try_deterministic_reply("120秒って何分？", self.context("120秒って何分？")), "2分。")
        self.assertEqual(try_deterministic_reply("80の25%は？", self.context("80の25%は？")), "20。")
        self.assertEqual(try_deterministic_reply("2031-01-02と2031-01-05の差は何日？", self.context("2031-01-02と2031-01-05の差は何日？")), "3日。")

    def test_greeting_and_ordinary_conversation_boundary(self):
        self.assertEqual(try_deterministic_reply("よお", self.context("よお")), "よお。")
        self.assertIsNone(try_deterministic_reply("ストレンジって常に惨めだよね", self.context("ストレンジって常に惨めだよね")))
        self.assertIsNone(try_deterministic_reply("14Bと7Bどっちがいい？", self.context("14Bと7Bどっちがいい？")))

    def test_direct_self_preference_is_revisable_not_empty_fallback(self):
        reply = try_deterministic_reply("お前に好みはないの？", self.context("お前に好みはないの？"))
        self.assertIn("ある。", reply)
        self.assertIn("判断も変える", reply)
        self.assertNotIn("好みはない", reply)
        self.assertIsNone(try_deterministic_reply("『お前に好みはないの？』を英訳して", self.context("『お前に好みはないの？』を英訳して")))

    def test_prepare_turn_bypasses_model_for_fast_path(self):
        with patch.object(tail, "extract_interpretation", side_effect=AssertionError("model path used")):
            reply, complete, memory, scene, warning = tail.prepare_turn([], "よお", None)
        self.assertEqual((reply, complete, memory, scene, warning), ("よお。", True, None, None, None))

    def test_ollama_stopped_non_target_has_honest_fallback(self):
        with patch.object(tail, "call_ollama", side_effect=RuntimeError("Ollama に接続できません。Ollama を起動してから、もう一度試してください。")):
            reply, complete = tail.generate_reply([], "ストレンジって常に惨めだよね")
        self.assertEqual(reply, "今は会話モデルが止まってるから、この質問は返せん。")
        self.assertTrue(complete)

    def test_code_blocks_are_untouched_by_fast_path(self):
        code = "```python\nprint('hello')\n```"
        self.assertIsNone(try_deterministic_reply("コードを書いて", self.context("コードを書いて")))
        self.assertEqual(tail.phase7_postprocess_reply([], "コードを書いて", code)[0], code)


if __name__ == "__main__":
    unittest.main()
