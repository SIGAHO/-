import unittest

from breaktail_retry_context import build_retry_messages, estimate_tokens


class RetryContextTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            {"role": "system", "content": "人格: あたし。確認済み: 予算6000円。原文記憶: 部品待ち。"},
            {"role": "user", "content": "時計のがんぎ車を作ってる"},
            {"role": "assistant", "content": "がんぎ車の設計だな"},
            {"role": "user", "content": "これまだ完成してないんだ"},
            {"role": "assistant", "content": "完成前なんだね"},
            {"role": "user", "content": "さっきの部品はどうなった？"},
        ]

    def test_retry_keeps_persona_evidence_and_history(self):
        messages, audit = build_retry_messages(self.messages, "勝手な質問を足さない", 4096)
        self.assertTrue(audit["repair_rule_injected"])
        self.assertEqual(audit["dropped_history_messages"], 0)
        self.assertIn("原文記憶", messages[0]["content"])
        self.assertIn("人格: あたし", messages[0]["content"])
        self.assertEqual(messages[1:-1], self.messages[1:-1])
        self.assertEqual(messages[-1], self.messages[-1])

    def test_overflow_discards_oldest_pair_but_keeps_evidence(self):
        messages, audit = build_retry_messages(self.messages, "禁止事項の再確認。" * 18, 640, reserve=64)
        self.assertGreater(audit["dropped_history_messages"], 0)
        self.assertIn("確認済み: 予算6000円", messages[0]["content"])
        self.assertEqual(messages[-1]["content"], "さっきの部品はどうなった？")
        self.assertLessEqual(estimate_tokens(messages), 576)

    def test_overflow_rule_falls_back_to_valid_original(self):
        messages, audit = build_retry_messages(self.messages, "指定" * 1500, 2048)
        self.assertFalse(audit["repair_rule_injected"])
        self.assertEqual(messages, self.messages)
        self.assertEqual(audit["reason"], "repair_rule_exceeds_context_budget")

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            build_retry_messages([{"role": "user", "content": "x"}], "rule", 4096)

    def test_original_is_unchanged(self):
        import copy
        old = copy.deepcopy(self.messages)
        build_retry_messages(self.messages, "repair", 4096)
        self.assertEqual(self.messages, old)


if __name__ == "__main__":
    unittest.main()
