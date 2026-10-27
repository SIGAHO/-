"""Human-requested wiring regressions; scripted replies are not quality labels."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter, ModelError
from companion_core.models import SourceType


class RecentContextTests(unittest.TestCase):
    def session(self, replies=('参加するの？', '走る側か。', '準備は万端？', 'わかった。')):
        session = ChatSession(FakeModelAdapter(replies))
        # Isolate raw-context wiring from policy candidate ranking: these
        # historical scripted questions intentionally violate the new policy.
        # Full PolicyVerifier is exercised by test_alignment, without this mock.
        patcher = patch.object(session.policy_verifier, 'verify', return_value={'issues': [], 'adherent': True})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(session.close)
        return session

    def cpu(self, request):
        return json.loads(request[0]['content'].split('CPU_CONTEXT\n')[1])

    def test_marathon_participation_keeps_raw_object_and_question(self):
        chat = self.session()
        chat.turn('今日はマラソン大会や！')
        chat.turn('参加するの！')
        request = chat.adapter.requests[-1]
        self.assertEqual(request[1:-1], [
            {'role': 'user', 'content': '今日はマラソン大会や！'},
            {'role': 'assistant', 'content': '参加するの？'}])
        self.assertEqual(self.cpu(request)['intent'], 'continuation')
        self.assertEqual(self.cpu(request)['previous_assistant'], '参加するの？')

    def test_role_clarification_keeps_participation_context(self):
        chat = self.session()
        for text in ('今日はマラソン大会や！', '参加するの！', 'ランナーとして'):
            chat.turn(text)
        request = chat.adapter.requests[-1]
        self.assertIn('今日はマラソン大会や！', [m['content'] for m in request])
        self.assertIn('参加するの！', [m['content'] for m in request])
        self.assertEqual(self.cpu(request)['intent'], 'continuation')
        self.assertIsNone(self.cpu(request)['topic'])

    def test_yes_reply_keeps_last_question(self):
        chat = self.session()
        for text in ('今日はマラソン大会や！', '参加するの！', 'ランナーとして', 'ああ'):
            chat.turn(text)
        request = chat.adapter.requests[-1]
        self.assertEqual(request[-2], {'role': 'assistant', 'content': '準備は万端？'})
        self.assertEqual(self.cpu(request)['previous_assistant'], '準備は万端？')
        self.assertEqual(self.cpu(request)['session_recall'], [])

    def test_continuation_does_not_resurrect_old_topic_or_recall(self):
        for text in ('ああ', 'それ', '参加するの！', 'ランナーとして'):
            with self.subTest(text=text):
                chat = self.session(('わかった。',) * 8)
                chat.turn('古い望遠鏡の計画')
                for i in range(5):
                    chat.turn(f'話を変える。今日の報告{i}')
                chat.turn(text)
                request = chat.adapter.requests[-1]
                cpu = self.cpu(request)
                self.assertNotIn('古い望遠鏡', json.dumps(request, ensure_ascii=False))
                self.assertIsNone(cpu['topic'])
                self.assertEqual(cpu['memory'], [])
                self.assertEqual(cpu['session_recall'], [])
                self.assertEqual(cpu['salient_experiences'], [])

    def test_four_raw_turns_pinned_even_over_soft_budget(self):
        chat = self.session(('本文。',) * 6)
        texts = [f'報告{i}:' + '長' * 1800 for i in range(5)]
        for text in texts:
            chat.turn(text)
        ctx = chat.core.handle('ああ')
        request = chat.prompts.build(ctx, chat.core.events.events, history_chars=10)
        self.assertEqual([m['content'] for m in request[1:-1] if m['role'] == 'user'], texts[-4:])
        self.assertEqual(len(request[1:-1]), 8)
        self.assertEqual(sum(m['content'] == 'ああ' for m in request), 1)

    def test_ambiguous_retorts_keep_raw_context_and_cpu_referent(self):
        for text in ('は？', '？？'):
            chat = self.session(('直前の返答。',))
            chat.turn('今日は大会や！')
            ctx = chat.core.handle(text)
            request = chat.prepare_reply(ctx, chat.core.events.events)
            self.assertEqual(request[-2]['content'], '直前の返答。')
            self.assertEqual(self.cpu(request)['previous_assistant'], '直前の返答。')
            self.assertIn('直前の返答', chat.generate_reply(ctx, request))
            self.assertEqual(len(chat.adapter.requests), 1)

    def test_greeting_no_old_auxiliary_topic_but_keeps_recent_raw(self):
        chat = self.session(('わかった。',) * 8)
        chat.turn('古い望遠鏡の計画')
        for i in range(5):
            chat.turn(f'話を変える。今日の報告{i}')
        chat.turn('おはよう')
        request = chat.adapter.requests[-1]
        cpu = self.cpu(request)
        self.assertNotIn('古い望遠鏡', json.dumps(request, ensure_ascii=False))
        self.assertIsNone(cpu['topic'])
        self.assertEqual(cpu['session_recall'], [])
        self.assertEqual(cpu['memory'], [])
        self.assertIn('話を変える。今日の報告4', [m['content'] for m in request])

    def test_restart_pins_raw_turns_and_explicit_recall_works(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(['参加するの？']), path)
            chat.turn('今日はマラソン大会や！')
            chat.close()
            chat = ChatSession(FakeModelAdapter(['わかった。', '記録を確認した。']), path)
            try:
                chat.turn('参加するの！')
                self.assertEqual(chat.adapter.requests[-1][1]['content'], '今日はマラソン大会や！')
                chat.turn('前にマラソン大会の話したよな？')
                self.assertTrue(self.cpu(chat.adapter.requests[-1])['session_recall'])
                self.assertFalse(any(m.source == SourceType.ASSISTANT_GENERATED for m in chat.core.memory.items))
            finally:
                chat.close()

    def test_external_followup_still_uses_knowledge_gate(self):
        chat = self.session()
        chat.turn('今日はマラソン大会や！')
        self.assertIn('未確認', chat.turn('その大会の参加費は？'))
        self.assertEqual(len(chat.adapter.requests), 1)


class StyleFailOpenTests(unittest.TestCase):
    def run_reply(self, original, rewrite):
        fake = FakeModelAdapter([original, rewrite])
        chat = ChatSession(fake)
        self.addCleanup(chat.close)
        reply = chat.turn('ああ')
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(chat.core.last_assistant, reply)
        self.assertFalse(any(e['kind'] == 'model_failure' for e in chat.fio.experiences.all()))
        return reply, chat

    def test_repeated_politeness_does_not_stop_conversation(self):
        text = '準備はできています。朝から走ります。'
        reply, chat = self.run_reply(text, text)
        self.assertEqual(reply, text)
        self.assertTrue(chat.last_response_meta['fail_open'])
        self.assertEqual(chat.last_response_meta['remaining_issues'], ['excessive_formality'])

    def test_choose_fewer_issues_before_shorter_candidate(self):
        reply, _ = self.run_reply('確認します。準備します。' + '長' * 321, '確認します。準備します。')
        self.assertEqual(reply, '確認します。準備します。')

    def test_never_truncate_meaningful_body_or_code(self):
        text = '```python\n' + 'print(123)\n' * 40 + '```'
        reply, _ = self.run_reply(text, text)
        self.assertEqual(reply, text)

    def test_only_boilerplate_does_not_become_empty(self):
        text = '何か手伝えることがありますか？'
        reply, chat = self.run_reply(text, text)
        self.assertEqual(reply, text)
        self.assertTrue(chat.last_response_meta['fail_open'])

    def test_safe_tail_removed_and_substantive_sentence_retained(self):
        text = '明日10時に集合。詳しく教えていただけますか？'
        reply, _ = self.run_reply(text, text)
        self.assertEqual(reply, '明日10時に集合。')

    def test_empty_invalid_timeout_are_generation_failures(self):
        for failure in ('', None, '\ud800', ModelError('timeout')):
            with self.subTest(failure=repr(failure)):
                chat = ChatSession(FakeModelAdapter())
                self.addCleanup(chat.close)
                with patch.object(chat.adapter, 'generate', side_effect=['確認します。準備します。', failure]):
                    with self.assertRaises(ModelError):
                        chat.turn('ああ')
                self.assertIsNone(chat.core.last_assistant)
                self.assertEqual(len(chat.core.events.events), 1)


if __name__ == '__main__':
    unittest.main()
