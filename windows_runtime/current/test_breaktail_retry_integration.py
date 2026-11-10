"""Ensure real reply regeneration reuses the evidence-grounded input."""
import unittest
from unittest.mock import patch

from test_model_isolation import ModelIsolatedCase
import breaktail_v02 as tail
from breaktail_working_state import new_working_state


class RetryIntegrationTests(ModelIsolatedCase):
    def test_generate_reply_retry_keeps_old_user_turns_and_memory(self):
        initial = [
            {"role": "system", "content": "人格: あたし。保存された本人の事実: まだ未完成。"},
            {"role": "user", "content": "脱進機の部品を作ってる"},
            {"role": "assistant", "content": "部品を作ってるのか。"},
            {"role": "user", "content": "今日も削ったよ"},
        ]
        generated = [
            {"message": {"content": "そうなんだ。何か質問ある？"}, "done_reason": "stop"},
            {"message": {"content": '{"sentences":["今日も削ったのか、だいぶ進んだな。"]}'},
             "done_reason": "stop"},
        ]
        calls = []

        def mock_ollama(messages, *args, **kwargs):
            calls.append(messages)
            return generated.pop(0)

        with patch.object(tail, "build_reply_messages", return_value=initial), \
             patch.object(tail, "call_ollama", side_effect=mock_ollama), \
             patch.object(tail, "contract_violations", side_effect=[
                 ["unrequested_question"], []
             ]), \
             patch.object(tail, "review_pragmatics", return_value={"hits": []}), \
             patch.object(tail, "log_turn"), \
             patch.object(tail, "load_profile", return_value=None):
            tail.generate_reply(
                initial[1:3], "今日も削ったよ",
                working_state=new_working_state(),
            )
        self.assertEqual(len(calls), 2)
        retry = calls[1]
        self.assertIn("保存された本人の事実: まだ未完成", retry[0]["content"])
        self.assertIn("脱進機の部品を作ってる", [x["content"] for x in retry])
        self.assertEqual(retry[-1]["content"], "今日も削ったよ")


if __name__ == "__main__":
    unittest.main()
