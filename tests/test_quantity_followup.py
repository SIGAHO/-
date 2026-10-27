"""User-provided numeric answers are conversation, not external evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.intent import IntentRouter
from companion_core.model_adapter import FakeModelAdapter
from companion_core.models import SourceType


class QuantityFollowupTests(unittest.TestCase):
    def test_actual_marathon_conversation_reaches_model_with_raw_question(self):
        fake = FakeModelAdapter(['どうだった？', 'タイムはどうだった？', '7キロ走ったんだね。'])
        chat = ChatSession(fake)
        self.addCleanup(chat.close)
        chat.turn('マラソン大会終わったわ')
        chat.turn('４５４位！商品なし！')
        with patch.object(chat.core.knowledge, 'evaluate', side_effect=AssertionError('external gate called')):
            self.assertEqual(chat.turn('7キロ５０分くらい？'), '7キロ走ったんだね。')
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual(fake.requests[-1][-2]['content'], 'タイムはどうだった？')
        self.assertEqual(fake.requests[-1][-1]['content'], '7キロ５０分くらい？')
        self.assertFalse(chat.last_response_meta['unverified'])

    def test_measurement_hedges_answer_previous_question(self):
        for text in ('7キロ５０分くらい？', '７km ５０分ぐらい?', '50分かな？', '1時間10分ほど？'):
            with self.subTest(text=text):
                self.assertEqual(IntentRouter().route(text, previous_assistant='タイムはどうだった？'), 'continuation')

    def test_factual_questions_still_gate_even_after_time_question(self):
        for text in ('7キロ50分は平均より速い？', 'その大会の制限時間は？', '7キロの世界記録を教えて',
                     '7キロ50分の消費カロリーは？', '地球は丸い？'):
            with self.subTest(text=text):
                self.assertEqual(IntentRouter().route(text, previous_assistant='タイムはどうだった？'), 'external_knowledge')

    def test_no_measurement_question_keeps_existing_factual_route(self):
        for prior in (None, '何を調べたい？', 'タイムの資料はまだ未確認。'):
            self.assertEqual(IntentRouter().route('50分くらい？', previous_assistant=prior), 'external_knowledge')

    def test_cpu_clock_and_arithmetic_still_take_priority(self):
        for text in ('8時まであと何分？', '2+3は？'):
            self.assertEqual(IntentRouter().route(text, previous_assistant='タイムはどうだった？'), 'time_calculation')

    def test_restart_restores_question_without_promoting_ai_to_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(['タイムはどうだった？']), path)
            chat.turn('大会を走った')
            chat.close()
            chat = ChatSession(FakeModelAdapter(['なるほど。']), path)
            try:
                self.assertEqual(chat.turn('7キロ５０分くらい？'), 'なるほど。')
                self.assertEqual(chat.core.topic.last_decision, 'route_bypass')
                self.assertFalse(any(m.source == SourceType.ASSISTANT_GENERATED for m in chat.core.memory.items))
                self.assertFalse(any(f.source == SourceType.ASSISTANT_GENERATED for f in chat.core.state.active.values()))
                expected_topic = chat.core.topic.current().label
                chat.core.replay()
                self.assertEqual(chat.core.topic.current().label, expected_topic)
            finally:
                chat.close()


if __name__ == '__main__':
    unittest.main()
