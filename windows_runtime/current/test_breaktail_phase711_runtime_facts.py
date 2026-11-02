import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import breaktail_fact_resolver as resolver
from breaktail_runtime_context import build_runtime_context, deterministic_evaluate
from breaktail_runtime_facts import (
    FactStore, RuntimeFact, collect_local_service, fact,
)
from breaktail_self import build_self_context, ground_self_reply


NOW = datetime(2031, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=9)))
CAPABILITIES = {
    "runtime_clock": "available", "vision_state": "not_connected",
    "can_observe_screen_now": False, "can_request_avatar_move_now": False,
    "can_request_file_operation_now": False, "keyboard_observed": False,
    "can_request_web_search_now": False, "search_state": "not_attempted",
    "search_observation": None, "operation_completion": "verified result required",
}


def keyed(context):
    return {item["key"]: item for item in context["facts"]}


class RuntimeFactSelectionTests(unittest.TestCase):
    def build(self, text, **kwargs):
        return build_runtime_context(text, CAPABILITIES, store=FactStore(), now=NOW, **kwargs)

    def test_only_clock_capabilities_and_operation_are_resident(self):
        context = self.build("猫かわいい")
        keys = set(keyed(context))
        self.assertEqual(keys, {
            "clock.current_datetime_iso", "clock.current_date", "clock.current_year",
            "clock.current_time", "clock.timezone", "capabilities",
            "operation.current", "operation.last_result",
        })

    def test_ram_is_injected_only_for_ram_question(self):
        fake = fact("system.memory", {"available_gib": 7.25}, "test")
        with patch("breaktail_runtime_context.collect_system_memory", return_value=fake) as collector:
            ram = self.build("RAM余ってる？")
            ordinary = self.build("猫かわいい")
        self.assertEqual(keyed(ram)["system.memory"]["value"]["available_gib"], 7.25)
        self.assertNotIn("system.memory", keyed(ordinary))
        self.assertEqual(collector.call_count, 1)

    def test_system_identity_is_selected_only_for_environment_question(self):
        context = self.build("今のOSは何？")
        self.assertIn("system.identity", keyed(context))
        ordinary = self.build("猫かわいい")
        self.assertNotIn("system.identity", keyed(ordinary))

    def test_disk_is_selected_only_for_capacity_question(self):
        context = self.build("ディスクの空き容量は？")
        self.assertIn("system.disk", keyed(context))
        ordinary = self.build("猫かわいい")
        self.assertNotIn("system.disk", keyed(ordinary))

    def test_cpu_is_selected_only_for_cpu_question(self):
        context = self.build("CPUコア数は？")
        self.assertIn("system.cpu", keyed(context))
        ordinary = self.build("猫かわいい")
        self.assertNotIn("system.cpu", keyed(ordinary))

    def test_unrelated_metrics_are_not_injected(self):
        context = self.build("Ollama生きてる？")
        self.assertNotIn("system.memory", keyed(context))
        self.assertNotIn("memory.state", keyed(context))
        self.assertNotIn("context.state", keyed(context))

    def test_memory_state_is_read_only_and_counts_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            original = '{"id":1}\n{"id":2}\n'
            path.write_text(original, encoding="utf-8")
            context = self.build("Memory何件？", memory_file=path)
            self.assertEqual(keyed(context)["memory.state"]["value"]["count"], 2)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_runtime_context_is_single_prompt_gateway(self):
        context = build_self_context(user_text="RAM余ってる？")
        self.assertEqual(context["prompt"].count("[Runtime Context]"), 1)
        self.assertIn("system.memory", context["runtime_context"]["selected_groups"])
        self.assertNotIn("[RuntimeFacts]", context["prompt"])
        self.assertNotIn("[OperationResults]", context["prompt"])

    def test_resolver_has_no_llm_dependency(self):
        source = inspect.getsource(resolver)
        self.assertNotIn("call_ollama(", source)
        self.assertNotIn("import ollama", source.lower())
        self.assertEqual(resolver.resolve_fact_groups("RAM余ってる？") - resolver.RESIDENT_FACTS,
                         {"system.memory"})


class RuntimeFactSemanticsTests(unittest.TestCase):
    def test_expired_ok_fact_becomes_stale(self):
        old = (NOW - timedelta(seconds=10)).isoformat()
        item = RuntimeFact("x", 12, old, "test", "ok", 2)
        self.assertEqual(item.as_dict(NOW)["status"], "stale")

    def test_failed_is_distinct_from_zero(self):
        zero = RuntimeFact("zero", 0, NOW.isoformat(), "test", "ok", 1).as_dict(NOW)
        failed = RuntimeFact("failed", None, NOW.isoformat(), "test", "failed", 1).as_dict(NOW)
        self.assertEqual(zero["value"], 0)
        self.assertEqual(zero["status"], "ok")
        self.assertIsNone(failed["value"])
        self.assertEqual(failed["status"], "failed")

    def test_not_connected_and_temporary_failure_are_distinct(self):
        with patch("breaktail_runtime_facts.socket.create_connection", side_effect=ConnectionRefusedError):
            disconnected = collect_local_service("service.x", "127.0.0.1", 1, NOW)
        with patch("breaktail_runtime_facts.socket.create_connection", side_effect=TimeoutError):
            temporary = collect_local_service("service.x", "127.0.0.1", 1, NOW)
        self.assertEqual(disconnected.status, "not_connected")
        self.assertEqual(temporary.status, "failed")

    def test_executed_without_verification_is_not_success(self):
        store = FactStore()
        store.start_operation("save")
        result = store.finish_operation("save", executed=True, verified=False, status="failed",
                                        verification_source="readback", result_summary="not verified")
        self.assertFalse(result.successful)
        self.assertFalse(store.operation_facts(NOW)[1].value["successful"])

    def test_verified_result_is_success(self):
        store = FactStore()
        result = store.finish_operation("save", executed=True, verified=True, status="ok",
                                        verification_source="readback", result_summary="verified")
        self.assertTrue(result.successful)
        self.assertTrue(store.operation_facts(NOW)[1].value["successful"])

    def operation_context(self, value):
        return {"capabilities": {}, "runtime_context": {"facts": [
            {"key": "operation.last_result", "value": value, "status": "ok"}
        ]}}

    def test_unverified_operation_reply_never_claims_success(self):
        value = {"operation": "memory.save", "executed": True, "verified": False, "successful": False}
        result = ground_self_reply("さっき保存成功した？", "成功したよ", self.operation_context(value))
        self.assertIn("成功したとは言えない", result["reply"])
        self.assertEqual(result["reason"], "operation_executed_unverified")

    def test_verified_operation_reply_can_claim_success(self):
        value = {"operation": "memory.save", "executed": True, "verified": True, "successful": True}
        result = ground_self_reply("さっき保存成功した？", "分からない", self.operation_context(value))
        self.assertIn("検証まで成功", result["reply"])
        self.assertEqual(result["reason"], "operation_verified_success")


class DeterministicRuntimeTests(unittest.TestCase):
    def test_ram_has_answer_ready_numeric_values(self):
        fake = fact("system.memory", {"available_bytes": 8 * 1024 ** 3,
                                      "available_gib": 8.0, "used_percent": 50.0}, "test")
        with patch("breaktail_runtime_context.collect_system_memory", return_value=fake):
            context = build_runtime_context("RAM余ってる？", CAPABILITIES, store=FactStore(), now=NOW)
        value = keyed(context)["system.memory"]["value"]
        self.assertEqual(value["available_gib"], 8.0)
        self.assertEqual(value["used_percent"], 50.0)

    def test_eight_seconds_minus_five_seconds_is_three(self):
        result = deterministic_evaluate("8秒と5秒の差は？", NOW)
        self.assertEqual(result["result"], 3)
        self.assertEqual(result["answer_core"], "差は3秒。")

    def test_comparison_and_unit_conversion(self):
        self.assertEqual(deterministic_evaluate("8と5はどっちが大きい？", NOW)["result"], 8)
        self.assertEqual(deterministic_evaluate("2時間は分にすると？", NOW)["result"], 120)

    def test_runtime_clock_date_differences(self):
        self.assertEqual(deterministic_evaluate("明日まであと何日？", NOW)["days"], 1)
        self.assertEqual(deterministic_evaluate("2031-01-10まであと何日？", NOW)["days"], 8)
        self.assertEqual(deterministic_evaluate("2031-01-02と2031-01-05の差は何日？", NOW)["days"], 3)

    def test_relative_dates_and_years_use_runtime_clock(self):
        self.assertEqual(deterministic_evaluate("明日は何日？", NOW)["date"], "2031-01-03")
        self.assertEqual(deterministic_evaluate("去年は何年？", NOW)["year"], 2030)
        self.assertEqual(deterministic_evaluate("来年は何年？", NOW)["year"], 2032)

    def test_deterministic_answer_core_overrides_model_recalculation(self):
        context = build_self_context(user_text="8秒と5秒の差は？")
        grounded = ground_self_reply("8秒と5秒の差は？", "差は2秒。", context)
        self.assertEqual(grounded["reply"], "差は3秒。")
        self.assertEqual(grounded["reason"], "deterministic_runtime_result")


if __name__ == "__main__":
    unittest.main()
