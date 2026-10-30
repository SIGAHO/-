import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter, OllamaAdapter, ModelError
from companion_core.emotion import EmotionEngine
from companion_core.models import SourceType


class ChatE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'events.jsonl'
        self.fake = FakeModelAdapter(['こんにちは。', '続きを話そう。'])
        self.chat = ChatSession(self.fake, self.path)

    def turn(self, text, **kwargs):
        return self.chat.turn(text, **kwargs)

    def test_interrupted_generation_preserves_input_and_records_cancellation(self):
        with patch.object(self.chat.adapter, 'generate', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.turn('今日は眠い')
        self.assertEqual([e.kind for e in self.chat.core.events.events], ['user_input'])
        self.assertEqual(self.chat.fio.recorder.records, [])
        self.assertIsNone(self.chat.fio.pending)
        self.assertEqual([e['kind'] for e in self.chat.fio.experiences.all()], ['generation_cancelled'])
        self.chat.close()
        reopened = ChatSession(FakeModelAdapter(['おかえり。']), self.path)
        self.addCleanup(reopened.close)
        self.assertEqual([e.kind for e in reopened.core.events.events], ['user_input'])
        self.assertEqual(reopened.turn('ただいま'), 'おかえり。')
        self.assertEqual([e['kind'] for e in reopened.fio.experiences.all()].count('generation_cancelled'), 1)

    def test_interrupted_retrieval_records_cancel_not_model_failure(self):
        with patch.object(self.chat.retrieval, 'retrieve', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.turn('富士山の高さを教えて')
        self.assertEqual([e.kind for e in self.chat.core.events.events], ['user_input'])
        self.assertIsNone(self.chat.fio.pending)
        self.assertIn('generation_cancelled', [e['kind'] for e in self.chat.fio.experiences.all()])
        self.assertNotIn('model_failure', [e['kind'] for e in self.chat.fio.experiences.all()])

    def test_interrupt_before_fio_begin_records_cancelled_input(self):
        with patch.object(self.chat.planner, 'observe', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.turn('今日は眠い')
        self.assertEqual([e.kind for e in self.chat.core.events.events], ['user_input'])
        self.assertIsNone(self.chat.fio.pending)
        self.assertEqual([e['kind'] for e in self.chat.fio.experiences.all()], ['generation_cancelled'])

    def test_cancelled_helper_does_not_mark_a_completed_turn(self):
        self.turn('ただいま')
        self.chat.fio.cancelled(self.chat.core)
        self.assertNotIn('generation_cancelled', [e['kind'] for e in self.chat.fio.experiences.all()])

    def test_smalltalk_roundtrip(self):
        self.assertEqual(self.turn('こんにちは'), 'こんにちは。')
        self.assertEqual([e.kind for e in self.chat.core.events.events], ['user_input', 'assistant_output'])
        self.assertEqual(self.fake.requests[0][-1], {'role': 'user', 'content': 'こんにちは'})

    def test_correction_retained(self):
        self.turn('赤じゃなくて青', correction_key='favorite.color')
        self.turn('覚えてる？')
        self.assertEqual(self.chat.core.state.active['favorite.color'].value, '青')
        self.assertIn('"favorite.color": "青"', self.fake.requests[-1][0]['content'])

    def test_topic_continuation(self):
        self.turn('望遠鏡を作りたい')
        topic = self.chat.core.topic.current()
        self.turn('それはどういう仕組み？')
        self.assertIs(self.chat.core.topic.current(), topic)

    def test_topic_switch(self):
        self.turn('望遠鏡を作りたい')
        topic = self.chat.core.topic.current()
        self.turn('話は変わるけど、パンを焼きたい')
        self.assertIsNot(self.chat.core.topic.current(), topic)

    def test_topic_return(self):
        self.turn('望遠鏡を作りたい')
        topic = self.chat.core.topic.current()
        self.turn('話は変わるけど、パンを焼きたい')
        self.turn('望遠鏡を作りたい')
        self.assertIs(self.chat.core.topic.current(), topic)

    def test_loop_completed(self):
        self.turn('あとでやる')
        self.assertEqual(len(self.chat.core.open_loops.active()), 1)
        self.turn('終わった')
        self.assertEqual(self.chat.core.open_loops.active(), [])

    def test_loop_not_completed(self):
        self.turn('あとでやる')
        self.turn('まだ終わってない')
        self.assertEqual(len(self.chat.core.open_loops.active()), 1)

    def test_memory_reference(self):
        self.turn('私の好きな色は紫')
        self.turn('好きな色を覚えてる？')
        self.assertIn('私の好きな色は紫', self.fake.requests[-1][0]['content'])

    def test_emotion_continuity(self):
        self.turn('最悪')
        self.turn('こんにちは')
        self.assertGreater(self.chat.core.emotion.state.irritation, 0)
        self.assertLess(self.chat.core.emotion.state.valence, 0)

    def test_ai_falsehood_never_promoted(self):
        self.chat.adapter = FakeModelAdapter(['今年は1900年で、あなたは医者です。'])
        self.turn('こんにちは')
        self.assertFalse(any(m.source == SourceType.ASSISTANT_GENERATED for m in self.chat.core.memory.items))
        self.assertFalse(any('1900' in str(f.value) or '医者' in str(f.value) for f in self.chat.core.state.active.values()))
        restarted = ChatSession(FakeModelAdapter(), self.path)
        self.assertFalse(any('医者' in m.text for m in restarted.core.memory.items))
        restarted.turn('私の職業は？')
        self.assertIn('AI誤答を事実化せず', restarted.adapter.requests[0][0]['content'])

    def test_restart_replay(self):
        self.turn('あとでやる')
        self.turn('赤じゃなくて青', correction_key='favorite.color')
        before = self.path.read_bytes()
        restarted = ChatSession(FakeModelAdapter(), self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(restarted.core.state.active['favorite.color'].value, '青')
        self.assertEqual(restarted.core.emotion.state.to_dict(), self.chat.core.emotion.state.to_dict())
        self.assertEqual([m.text for m in restarted.core.memory.items], [m.text for m in self.chat.core.memory.items])
        self.assertEqual([m.created_at for m in restarted.core.memory.items], [m.created_at for m in self.chat.core.memory.items])
        self.assertEqual(restarted.core.topic.current().label, self.chat.core.topic.current().label)
        self.assertEqual(restarted.core.topic.current().last_seen, self.chat.core.topic.current().last_seen)
        self.assertEqual([x.created_at for x in restarted.core.open_loops.loops],
                         [x.created_at for x in self.chat.core.open_loops.loops])
        self.assertEqual(len(restarted.core.open_loops.active()), 1)
        restarted.turn('好きな色は？')
        self.assertTrue(any(m['role'] == 'assistant' for m in restarted.adapter.requests[0]))

    def test_failed_model_keeps_input_without_fake_reply(self):
        with patch.object(self.fake, 'generate', side_effect=ModelError('offline')):
            with self.assertRaises(ModelError):
                self.turn('あとでやる')
        self.assertEqual([e.kind for e in self.chat.core.events.events], ['user_input'])
        self.assertTrue(ChatSession(FakeModelAdapter(), self.path).core.open_loops.active())

    def test_empty_input_no_event(self):
        with self.assertRaises(ValueError):
            self.turn('   ')
        self.assertEqual(self.chat.core.events.events, [])

    def test_correction_current_user_occurs_once(self):
        self.turn('赤じゃなくて青', correction_key='favorite.color')
        self.assertEqual(sum(m['content'] == '赤じゃなくて青' for m in self.fake.requests[0]), 1)

    def test_replaced_correction_is_archived_on_replay(self):
        self.turn('赤じゃなくて青', correction_key='favorite.color')
        self.turn('青じゃなくて緑', correction_key='favorite.color')
        restarted = ChatSession(FakeModelAdapter(), self.path)
        active = [m.text for m in restarted.core.memory.retrieve('favorite.color')]
        self.assertIn('favorite.color = 緑', active)
        self.assertNotIn('favorite.color = 青', active)

    def test_corrupt_log_fails_without_truncation(self):
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            ChatSession(FakeModelAdapter(), self.path)
        self.assertEqual(self.path.read_text(), '{broken')

    def test_many_turns_and_restart(self):
        for i in range(25):
            self.turn(f'望遠鏡について{i}番目の質問です')
        restarted = ChatSession(FakeModelAdapter(), self.path)
        restarted.turn('その続きは？')
        self.assertEqual(len(restarted.core.events.events), 52)
        self.assertLessEqual(sum(len(m['content']) for m in restarted.adapter.requests[0][1:-1]), 6000)

    def test_cli_utf8_input_output_and_persistence(self):
        import subprocess
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'chat.py'),
                                 '--fake', '--event-log', str(self.path)],
                                input='こんにちは\n/exit\n', text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('こんにちは', result.stdout)
        events = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[0]['payload']['text'], 'こんにちは')
        self.assertEqual(events[1]['source'], 'assistant_generated')


class AdapterTests(unittest.TestCase):
    def test_http_contract(self):
        import io
        with patch('companion_core.model_adapter.urlopen', return_value=io.BytesIO(json.dumps({'done': True, 'message': {'content': '返答'}}).encode())) as call:
            self.assertEqual(OllamaAdapter().generate([{'role': 'user', 'content': '質問'}]), '返答')
        request = call.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/api/chat'))
        body = json.loads(request.data)
        self.assertFalse(body['stream'])
        self.assertEqual(body['model'], 'qwen2.5:14b')
        self.assertEqual(body['messages'][0]['content'], '質問')

    def test_unavailable(self):
        with patch('companion_core.model_adapter.urlopen', side_effect=URLError('offline')):
            with self.assertRaises(ModelError):
                OllamaAdapter().generate([])

    def test_invalid_responses(self):
        import io
        for body in (b'not-json', b'{}', b'{"done":true,"message":{"content":""}}', b'[]', b'{"message":{"content":"x"}}'):
            with self.subTest(body=body), patch('companion_core.model_adapter.urlopen', return_value=io.BytesIO(body)):
                with self.assertRaises(ModelError):
                    OllamaAdapter().generate([])

    def test_generation_limit_is_failure_not_a_completed_reply(self):
        import io
        for reason, ok in [('length', False), ('stop', True), (None, True)]:
            payload = {'done': True, 'message': {'content': 'ここまで'}}
            if reason is not None:
                payload['done_reason'] = reason
            with self.subTest(reason=reason), patch('companion_core.model_adapter.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
                if ok:
                    self.assertEqual(OllamaAdapter().generate([]), 'ここまで')
                else:
                    with self.assertRaises(ModelError):
                        OllamaAdapter().generate([])

    def test_truncated_generation_is_not_committed_as_assistant_reply(self):
        import io
        payload = {'done': True, 'done_reason': 'length', 'message': {'content': '不完全な返答'}}
        chat = ChatSession(OllamaAdapter())
        try:
            with patch('companion_core.model_adapter.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ModelError):
                    chat.turn('こんにちは')
            self.assertEqual([e.kind for e in chat.core.events.events], ['user_input'])
            self.assertEqual(chat.fio.recorder.records, [])
        finally:
            chat.close()

    def test_incomplete_http_and_invalid_utf8_preserve_failure_and_allow_next_turn(self):
        import io
        from http.client import IncompleteRead, BadStatusLine
        failures = [IncompleteRead(b'partial', 4), BadStatusLine('invalid'), b'\xff']
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                chat = ChatSession(OllamaAdapter())
                try:
                    mock = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': io.BytesIO(failure)}
                    with patch('companion_core.model_adapter.urlopen', **mock):
                        with self.assertRaises(ModelError):
                            chat.turn('こんにちは')
                    self.assertEqual([e.kind for e in chat.core.events.events], ['user_input'])
                    self.assertIsNone(chat.fio.pending)
                    self.assertTrue(any(e['kind'] == 'model_failure' for e in chat.fio.experiences.all()))
                    chat.adapter = FakeModelAdapter(['おかえり。'])
                    self.assertEqual(chat.turn('ただいま'), 'おかえり。')
                finally:
                    chat.close()

    def test_environment_and_argument_priority(self):
        with patch.dict('os.environ', {'BREAKTAIL_MODEL': 'env-model', 'OLLAMA_HOST': 'localhost:1234'}):
            self.assertEqual(OllamaAdapter().model, 'env-model')
            self.assertEqual(OllamaAdapter('argument-model').model, 'argument-model')
            self.assertEqual(OllamaAdapter().base_url, 'http://localhost:1234')


class EmotionBoundaryTests(unittest.TestCase):
    def test_negation_and_quotes_independent_of_domain(self):
        for text in ['面白くない', '最高ではない', '「馬鹿」と言われた', '『うざい』という台詞']:
            emotion = EmotionEngine()
            value = emotion.observe_user(text)
            if '「' in text or '『' in text:
                self.assertEqual(value.irritation, 0)
            else:
                self.assertLessEqual(value.valence, 0)


if __name__ == '__main__':
    unittest.main()
