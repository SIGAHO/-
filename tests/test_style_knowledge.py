"""Structural contracts requested by the user, not conversational ground truth.

No training occurs; scripted model strings only exercise filtering and wiring.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.daemon import CompanionDaemon
from companion_core.knowledge import KnowledgeGate
from companion_core.memory import MemoryEngine
from companion_core.model_adapter import FakeModelAdapter, ModelError
from companion_core.models import SourceType, Scope, Status, MemoryItem
from companion_core.state import StateEngine
from companion_core.style import StyleProfile, StyleValidator


class StyleContractTests(unittest.TestCase):
    def context(self, session, text):
        ctx = session.core.handle(text)
        messages = session.prompts.build(ctx, session.core.events.events)
        cpu = json.loads(messages[0]['content'].split('CPU_CONTEXT\n')[1])
        return messages, cpu

    def test_profile_every_turn_in_fifteen_conversational_directions(self):
        # Inputs are independent plumbing probes; no desired model utterances.
        directions = {
            'joy': 'よっしゃ', 'retort': 'そこは違うってば', 'hurry': '出発まで時間ない',
            'school': '授業に向かう', 'assignment': '作文を手伝って',
            'technical': '非同期処理の設計を考えたい', 'correction': '赤じゃなくて青',
            'smalltalk': '今日は眠い', 'excitement': 'きたーー！！', 'short': 'うん',
            'no_question_tail': '報告だけだよ', 'no_assistantese': '作業できた',
            'no_excessive_politeness': '気楽に話そう', 'concise': '一言で返して',
            'substantive_question_only': 'ちょっと休む',
        }
        session = ChatSession(FakeModelAdapter())
        for direction, text in directions.items():
            with self.subTest(direction=direction):
                messages, cpu = self.context(session, text)
                self.assertEqual(set(cpu['style']['profile']), set(vars(StyleProfile())))
                self.assertLess(cpu['style']['profile']['assistantese'], .05)
                self.assertLessEqual(cpu['style']['max_chars'], 320)
                for rule in ['毎回質問で締めない', '短文中心', '軽いツッコミ', '過剰な丁寧語は禁止', 'テンポと語彙']:
                    self.assertIn(rule, messages[0]['content'])

    def test_profile_validation_and_environment(self):
        for invalid in [-1, 2, float('nan'), float('inf'), True, 'casual']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                StyleProfile(formality=invalid)
        with patch.dict('os.environ', {'BREAKTAIL_STYLE': '{"energy":0.4}'}):
            self.assertEqual(ChatSession(FakeModelAdapter()).prompts.style.profile.energy, .4)

    def test_explicit_detail_has_more_room(self):
        session = ChatSession(FakeModelAdapter())
        self.assertGreater(session.prompts.style.context('詳しく手順を説明して')['max_chars'],
                           session.prompts.style.context('短く')['max_chars'])

    def test_assistantese_regeneration_e2e_only_final_saved(self):
        fake = FakeModelAdapter(['できました。何か手伝えることがありますか？', 'できたよ。'])
        session = ChatSession(fake)
        self.assertEqual(session.turn('作業終わった'), 'できたよ。')
        self.assertEqual(len(fake.requests), 2)
        self.assertTrue(session.last_response_meta['regenerated'])
        self.assertEqual(json.loads(fake.requests[1][1]['content'])['draft'], 'できました。何か手伝えることがありますか？')
        self.assertEqual(len(fake.requests[1]), 2)
        self.assertEqual([e.payload['text'] for e in session.core.events.events if e.kind == 'assistant_output'], ['できたよ。'])
        self.assertFalse(any('できました' in m.text for m in session.core.memory.items))

    def test_repeated_boilerplate_tail_removed_after_single_retry(self):
        fake = FakeModelAdapter(['了解。詳しく教えていただけますか？'] * 2)
        session = ChatSession(fake)
        self.assertEqual(session.turn('始めるよ'), '了解。')
        self.assertEqual(len(fake.requests), 2)

    def test_empty_cleaned_rewrite_uses_only_safe_original_tail_deletion(self):
        fake = FakeModelAdapter(['保存できた。何か手伝えることがあったら言ってね。',
                                 '他に何か手伝えることはある？'])
        self.assertEqual(ChatSession(fake).turn('できたよ'), '保存できた。')
        self.assertEqual(len(fake.requests), 2)

    def test_non_tail_boilerplate_is_not_silently_rewritten(self):
        fake = FakeModelAdapter(['無理のない範囲で進めて。次は設定する。'] * 3)
        session = ChatSession(fake)
        with self.assertRaises(ModelError):
            session.turn('始めるよ')
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(len(session.core.events.events), 1)

    def test_mixed_substantive_tail_is_never_deleted(self):
        validator = StyleValidator()
        text = '無理のない範囲で、明日10時に集合してください。'
        self.assertEqual(validator.clean_tail(text), text)
        self.assertEqual(validator.clean_tail('![図](image.png)'), '![図](image.png)')
        self.assertEqual(validator.clean_tail('!重要。詳しく教えていただけますか？'), '!重要。')

    def test_excessive_politeness_and_length_trigger_one_retry(self):
        for bad in ['確認します。準備します。説明します。', '長' * 321]:
            with self.subTest(bad=bad[:10]):
                fake = FakeModelAdapter([bad, '準備できた。'])
                self.assertEqual(ChatSession(fake).turn('始めよう'), '準備できた。')
                self.assertEqual(len(fake.requests), 2)

    def test_useful_question_and_code_are_preserved(self):
        for reply in ['出発は何時？', '```python\nprint("hello")\n```']:
            fake = FakeModelAdapter([reply])
            self.assertEqual(ChatSession(fake).turn('作業する'), reply)
            self.assertEqual(len(fake.requests), 1)

    def test_regeneration_failure_keeps_input_only(self):
        session = ChatSession(FakeModelAdapter())
        with patch.object(session.adapter, 'generate', side_effect=['何か手伝えることがありますか？', ModelError('offline')]):
            with self.assertRaises(ModelError):
                session.turn('やった')
        self.assertEqual(len(session.core.events.events), 1)


class KnowledgeContractTests(unittest.TestCase):
    query = 'LUMEN ARC知ってる？'
    fact = 'LUMEN ARCは架空の楽曲。歌唱は仮の人物。'

    def test_unknown_name_bypasses_hallucinating_model(self):
        fake = FakeModelAdapter(['これは事実ですと捏造する'])
        session = ChatSession(fake)
        self.assertIn('未確認', session.turn(self.query))
        self.assertEqual(fake.requests, [])
        self.assertTrue(session.last_response_meta['unverified'])

    def test_common_katakana_is_not_a_named_work(self):
        session = ChatSession(FakeModelAdapter(['うん、そのテーマで構成しよう。']))
        self.assertEqual(session.turn('発表のテーマが尊敬という意味じゃない'), 'うん、そのテーマで構成しよう。')
        self.assertFalse(session.last_response_meta['unverified'])
        session.turn('学校の英語発表の構成を考えたい')
        self.assertFalse(session.core.handle('発表は自分が尊敬する作品についてだよ。テーマが尊敬って意味じゃない')['knowledge']['external_required'])

    def test_trusted_memory_needs_no_external_lookup_and_enters_prompt(self):
        fake = FakeModelAdapter(['記憶の資料では架空の楽曲だよ。'])
        session = ChatSession(fake)
        session.core.memory.add(self.fact, SourceType.VERIFIED_MEMORY)
        self.assertTrue(session.core.memory.has_reliable_context(self.query))
        self.assertEqual(session.turn(self.query), '記憶の資料では架空の楽曲だよ。')
        self.assertIn(self.fact, fake.requests[0][0]['content'])
        self.assertFalse(session.last_response_meta['unverified'])

    def test_ai_user_mentions_and_archived_records_are_not_external_evidence(self):
        for source in [SourceType.ASSISTANT_GENERATED, SourceType.USER_STATEMENT, SourceType.USER_CORRECTION]:
            memory = MemoryEngine()
            memory.items.append(MemoryItem(self.fact, source))
            self.assertFalse(memory.has_reliable_context(self.query))
        memory = MemoryEngine()
        memory.add(self.fact, SourceType.VERIFIED_MEMORY)
        memory.items[0].status = Status.ARCHIVED
        self.assertFalse(memory.has_reliable_context(self.query))

    def test_similar_text_cannot_destroy_provenance(self):
        for first, second in [(SourceType.USER_STATEMENT, SourceType.VERIFIED_MEMORY),
                              (SourceType.VERIFIED_MEMORY, SourceType.USER_STATEMENT)]:
            memory = MemoryEngine()
            memory.add(self.fact, first)
            memory.add(self.fact, second)
            self.assertEqual(len(memory.items), 2)
            self.assertTrue(memory.has_reliable_context(self.query))

    def test_title_alone_question_uncertainty_and_wrong_facet_are_insufficient(self):
        for text in ['LUMEN ARC', self.query, 'LUMEN ARCは楽曲かもしれない',
                     self.fact.replace('LUMEN', 'LUMENA'), self.fact.replace('ARC', 'ARCS')]:
            memory = MemoryEngine()
            memory.add(text, SourceType.VERIFIED_MEMORY)
            self.assertFalse(memory.has_reliable_context(self.query), text)
        memory = MemoryEngine()
        memory.add(self.fact, SourceType.VERIFIED_MEMORY)
        self.assertFalse(memory.has_reliable_context('LUMEN ARCの発売日は？'))

    def test_subject_and_requested_facet_must_both_match(self):
        memory = MemoryEngine()
        memory.add('LUMEN ARCの発売日は2020年1月1日。', SourceType.VERIFIED_MEMORY)
        self.assertTrue(memory.has_reliable_context('LUMEN ARCの発売日は？'))
        self.assertFalse(memory.has_reliable_context('LUMEN ARCの価格は？'))

    def test_negative_creator_statement_cannot_answer_identity(self):
        memory = MemoryEngine()
        memory.add('LUMEN ARCの作者は太郎ではない。', SourceType.VERIFIED_MEMORY)
        self.assertFalse(memory.has_reliable_context('LUMEN ARCの作者は誰？'))

    def test_state_source_gate(self):
        gate, memory = KnowledgeGate(), MemoryEngine()
        for source in [SourceType.VERIFIED_MEMORY, SourceType.RUNTIME, SourceType.USER_STATEMENT]:
            state = StateEngine()
            state.propose('LUMEN ARC', '架空の楽曲', source, Scope.SESSION)
            result = gate.evaluate(self.query, memory, state)
            self.assertEqual(result.external_required, source == SourceType.USER_STATEMENT)

    def test_multiple_entities_require_complete_evidence(self):
        memory = MemoryEngine()
        memory.add(self.fact, SourceType.VERIFIED_MEMORY)
        result = KnowledgeGate().evaluate('「LUMEN ARC」と「SOLAR BELL」の関係は？', memory, StateEngine())
        self.assertTrue(result.external_required)

    def test_unknown_japanese_title_and_indirect_reference(self):
        session = ChatSession(FakeModelAdapter())
        self.assertIn('未確認', session.turn('星屑航路って知ってる？'))
        self.assertIn('未確認', session.turn('その作者は誰？'))
        self.assertIn('未確認', session.turn('歌手は？'))
        self.assertIn('未確認', session.turn('霧笛航路について教えて'))

    def test_repeated_questions_and_restart_do_not_become_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            session = ChatSession(FakeModelAdapter(), path)
            session.turn(self.query)
            session.core.record_assistant_output(self.fact)
            restarted = ChatSession(FakeModelAdapter(), path)
            self.assertIn('未確認', restarted.turn('その歌手は誰？'))
            self.assertIn('未確認', restarted.turn(self.query))

    def test_daemon_uses_same_style_and_knowledge_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeModelAdapter(['何か手伝えることがありますか？', 'お、できた！'])
            daemon = CompanionDaemon(fake, Path(directory) / 'events.jsonl')
            try:
                self.assertEqual(daemon.turn('やったぞ'), 'お、できた！')
                self.assertEqual(len(fake.requests), 2)
                self.assertIn('未確認', daemon.turn(self.query))
                self.assertEqual(len(fake.requests), 2)
            finally:
                daemon.close()


if __name__ == '__main__':
    unittest.main()
