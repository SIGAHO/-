import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.intent import IntentRouter
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class CharacterRoutingTests(unittest.TestCase):
    def test_memory_and_source_phrasings_use_local_context(self):
        router = IntentRouter()
        self.assertEqual(router.route('先週カメラを買ったって言ったっけ？'), 'self_state_memory')
        self.assertEqual(router.route('その答えの出所は？'), 'self_state_memory')
        self.assertTrue(IntentRouter.provenance.search('その答えの出所は？'))
        self.assertEqual(router.route('カメラとは何？'), 'external_knowledge')

    def test_recent_denial_and_recall_are_not_external_lookup(self):
        router = IntentRouter()
        self.assertEqual(router.route('寝不足とは言ってないぞ。決めつけるな。'), 'casual_chat')
        self.assertEqual(router.route('今の話で俺は何を否定した？'), 'self_state_memory')
        self.assertEqual(router.route('寝不足とは何か教えて？'), 'external_knowledge')

    def test_generic_memory_query_is_not_itself_a_remembered_claim(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(), path)
            chat.turn('梨が好きだよ')
            chat.turn('木曜日に図書館へ行く')
            answer = chat.turn('記憶に入ってる。')
            self.assertIn('梨が好き', answer)
            self.assertIn('木曜日に図書館', answer)
            self.assertNotIn('記憶に入ってる', answer)
            source = chat.turn('その記憶の根拠は？')
            self.assertNotIn('記憶に入ってる', source)
            chat.close()
            chat = ChatSession(FakeModelAdapter(), path)
            try:
                answer = chat.turn('記憶に入ってる。')
                self.assertIn('梨が好き', answer)
                self.assertIn('木曜日に図書館', answer)
                self.assertNotIn('記憶に入ってる', answer)
            finally:
                chat.close()

    def test_refusal_and_recent_personal_question_do_not_trigger_web(self):
        router = IntentRouter()
        self.assertEqual(router.route('休めとは言わないで。今日は聞いてくれればいい。'), 'casual_chat')
        self.assertEqual(router.route('さっき俺は何に困っていた？'), 'self_state_memory')
        self.assertEqual(router.route('休めとはどういう意味？'), 'external_knowledge')

    def test_clock_offset_and_cross_midnight(self):
        chat = ChatSession(FakeModelAdapter())
        try:
            self.assertEqual(chat.turn('今7時10分、50分後は何時？'), '8時00分。')
            self.assertEqual(chat.turn('23:50、20分後は何時？'), '1日後の0時10分。')
            self.assertIn('CPUで確定できない', chat.turn('25時10分、50分後は何時？'))
        finally:
            chat.close()

    def test_raw_dialogue_provenance_records_only_real_history_ids(self):
        adapter = FakeModelAdapter(['そうなんだな。', 'おはよう。'])
        chat = ChatSession(adapter)
        try:
            chat.turn('俺は杉並に住んでいる。', event_id='first')
            chat.turn('おはよう。', event_id='second')
            raw = [x for x in chat.core.provenance.last['sources'] if x['kind'] == 'raw_dialogue']
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]['items'][0], {'turn_id': 'first', 'role': 'user'})
            self.assertFalse(raw[0]['verified'])
            self.assertNotIn('杉並', str(raw[0]))
            self.assertIn('直近の会話原文', chat.turn('その情報はどこから？'))
        finally:
            chat.close()

    def test_greeting_provenance_uses_filtered_prompt_memory(self):
        adapter = FakeModelAdapter(['青なんだな。', 'おかえり。'])
        chat = ChatSession(adapter)
        try:
            chat.turn('好きな色は青だよ')
            chat.turn('ただいま')
            kinds = [s['kind'] for s in chat.core.provenance.last['sources']]
            self.assertNotIn('memory', kinds)
            self.assertNotIn('session_recall', kinds)
            self.assertIn('"memory": []', adapter.requests[-1][0]['content'])
            self.assertNotIn('記憶（ユーザー申告を含む）', chat.turn('その情報はどこから？'))
        finally:
            chat.close()

    def test_memory_recall_keeps_declarative_favorite_after_restart(self):
        import tempfile
        from companion_core.models import SourceType
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(['青が好きなんだな。']), path)
            chat.turn('好きな色は青')
            chat.close()
            chat = ChatSession(FakeModelAdapter(), path)
            try:
                self.assertTrue(any(m.text == '好きな色は青' and m.source == SourceType.USER_STATEMENT for m in chat.core.memory.items))
                self.assertIn('好きな色は青', chat.turn('覚えてる？'))
            finally:
                chat.close()
            chat = ChatSession(FakeModelAdapter(), path)
            try:
                explanation = chat.turn('その情報はどこから？')
                self.assertIn('好きな色は青', explanation)
                self.assertNotIn('過去の会話引用', explanation)
            finally:
                chat.close()

    def test_memory_and_recall_provenance_do_not_truncate_negation(self):
        from companion_core.memory import MemoryEngine
        from companion_core.models import SourceType
        from companion_core.provenance import ProvenanceResponder
        text = '背景。' * 45 + '私は大会に参加したわけではない。'
        memory = MemoryEngine()
        memory.add(text, SourceType.USER_STATEMENT)
        answer, records = ProvenanceResponder.memory_answer(memory)
        self.assertEqual(records, [text])
        self.assertIn(text, answer)
        p = ProvenanceResponder()
        p.last = {'generated': True, 'sources': [{'kind': 'session_recall', 'items': [
            {'exchanges': [{'turn_id': 'user-42', 'user_source': 'user_statement', 'user_complete': True, 'user': text}]}]}]}
        self.assertIn(text, p.answer())

    def test_unavailable_external_fact_is_recorded_as_cpu_bypass(self):
        from companion_core.retrieval import RetrievalEngine
        chat = ChatSession(FakeModelAdapter(), retrieval=RetrievalEngine())
        try:
            answer = chat.turn('富士山の高さは何メートル？')
            self.assertIn('未確認', answer)
            self.assertTrue(chat.last_response_meta['cpu'])
            self.assertTrue(chat.last_response_meta['unverified'])
            self.assertTrue(chat.alignment_trace['verifier_result']['cpu_bypass'])
            self.assertFalse(chat.core.provenance.last['generated'])
            self.assertEqual(chat.adapter.requests, [])
            chat.turn('富士山の高さは何メートル？')
            explanation = chat.turn('その情報はどこから？')
            self.assertIn('disabled', explanation)
            self.assertIn('今回の外部検索', explanation)
            self.assertNotIn('過去の経験記録（未検証）', explanation)
        finally:
            chat.close()

    def test_jealousy_question_addressed_to_companion_is_not_web_search(self):
        from companion_core.intent import IntentRouter
        router = IntentRouter()
        self.assertEqual(router.route('お前、ちょっと嫉妬した？'), 'casual_chat')
        self.assertEqual(router.route('お前、ちょっと嫉妬する？'), 'casual_chat')
        self.assertEqual(router.route('友達は嫉妬した？'), 'external_knowledge')
        self.assertEqual(router.route('友達は入賞したよ。お前、ちょっと嫉妬した？'), 'casual_chat')
        self.assertEqual(router.route('富士山の高さは？お前、ちょっと嫉妬した？'), 'external_knowledge')

    def test_time_pair_accepts_exact_hours_and_rejects_invalid_times(self):
        from companion_core.cpu_answer import CPUAnswer
        cpu = CPUAnswer()
        facts = {'time.iso': '2026-10-30T08:00:00+09:00'}
        for text, expected in [('9時から10時まで何分？', '60分。'),
                               ('9時30分から10時まで何分？', '30分。'),
                               ('9時から10時15分まで何分？', '75分。'),
                               ('23時から1時まで何分？', '120分。')]:
            self.assertEqual(cpu.answer(text, facts), expected)
        self.assertIn('確定できない', cpu.answer('25時から10時まで何分？', facts))

    def test_fictional_character_examples_stay_out_of_memory(self):
        chat = ChatSession(FakeModelAdapter(['ただいま。']), prompt_mode='character')
        try:
            chat.turn('よお')
            requests = chat.adapter.requests[0]
            self.assertTrue(any('やきもち焼いた？' == m['content'] for m in requests))
            self.assertFalse(any('やきもち焼いた？' in item.text for item in chat.core.memory.items))
            self.assertFalse(any(e.payload.get('text') == 'やきもち焼いた？' for e in chat.core.events.events))
        finally:
            chat.close()

    def test_emotional_reaction_does_not_trigger_web_gate(self):
        self.assertEqual(IntentRouter().route('嫉妬した？'), 'casual_chat')
        self.assertEqual(IntentRouter().route('ちょっと嫉妬した？'), 'casual_chat')
        self.assertEqual(IntentRouter().route('嫉妬とは何？'), 'external_knowledge')
        self.assertEqual(IntentRouter().route('その記憶の根拠は？'), 'self_state_memory')
        self.assertTrue(IntentRouter.provenance.search('その記憶の根拠は？'))

    def test_recall_provenance_reports_input_without_claiming_entailment(self):
        from companion_core.provenance import ProvenanceResponder
        responder = ProvenanceResponder()
        responder.last = {'generated': True, 'sources': [{'kind': 'session_recall', 'items': [
            {'exchanges': [{'turn_id': 'user-42', 'user_source': 'user_statement', 'user_complete': True, 'user': '色は緑だ'},
                           {'turn_id': 'ai-1', 'user_source': 'assistant_generated', 'user': '根拠なき文'}]}]}]}
        answer = responder.answer()
        self.assertIn('色は緑だ', answer)
        self.assertIn('user-42', answer)
        self.assertNotIn('根拠なき文', answer)
        self.assertIn('一致までは保証していない', answer)

    def test_calculation_provenance_survives_replay(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(), path)
            self.assertEqual(chat.turn('8時42分から9時17分までは何分'), '35分。')
            chat.close()
            chat = ChatSession(FakeModelAdapter(), path)
            try:
                answer = chat.turn('その情報はどこから')
                self.assertIn('8時42分から9時17分', answer)
                self.assertIn('35分', answer)
            finally:
                chat.close()
