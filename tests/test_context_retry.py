import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class ContextRetryTests(unittest.TestCase):
    def test_minimal_experiment_keeps_real_roles_without_example_turns(self):
        adapter = FakeModelAdapter(['おかえり。', '眠いんだな。'])
        chat = ChatSession(adapter, prompt_mode='character-minimal')
        try:
            chat.turn('ただいま')
            chat.turn('眠い')
            messages = adapter.requests[-1]
            self.assertEqual([(m['role'], m['content']) for m in messages[1:]],
                             [('user', 'ただいま'), ('assistant', 'おかえり。'), ('user', '眠い')])
        finally:
            chat.close()

    def test_scene_examples_are_unapproved_system_data_not_user_messages(self):
        adapter = FakeModelAdapter(['おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-scene')
        try:
            chat.turn('ただいま')
            messages = adapter.requests[0]
            self.assertIn('創作された未承認の口調例', messages[0]['content'])
            self.assertEqual([(m['role'], m['content']) for m in messages[1:]], [('user', 'ただいま')])
        finally:
            chat.close()

    def test_sumanai_acknowledges_a_rejected_strategy(self):
        from companion_core.alignment import ConversationState, PolicyVerifier, ResponseSpec
        state = ConversationState('correction', None, 'negative', 'advise', 'rejected', 'medium', [])
        spec = ResponseSpec(acknowledge_misalignment=True)
        result = PolicyVerifier().verify('すまない、友達との付き合いは尊重する。', spec, state, '口出しはやめて')
        self.assertNotIn('missing_misalignment_acknowledgment', result['issues'])
        self.assertIn('missing_misalignment_acknowledgment', PolicyVerifier().verify('分かった。', spec, state)['issues'])

    def test_rejected_method_is_not_mistaken_for_an_advice_request(self):
        from companion_core.alignment import Acts, PolicyPlanner
        planner = PolicyPlanner()
        for text in ('方法は聞いてない。ただ眠いと言っただけ', '手順は求めていない', 'アドバイスは要らん'):
            with self.subTest(text=text):
                state = planner.observe(text, [])
                self.assertTrue(Acts.rejection.search(text))
                self.assertFalse(planner.plan(state, text).advice_allowed)
        state = planner.observe('やり方を教えてほしい', [])
        self.assertTrue(planner.plan(state, 'やり方を教えてほしい').advice_allowed)
        self.assertTrue(Acts.advice.search('疲れてるならゆっくり休んでください。'))
        self.assertFalse(Acts.advice.search('昨日はゆっくり休んでた。'))

    def test_rejection_scope_does_not_cancel_separate_advice_request(self):
        from companion_core.alignment import PolicyPlanner
        planner = PolicyPlanner()
        for text in ('質問はいらない。手順は教えて', '質問はいらないけど手順を教えて', 'アドバイスはいらないわけじゃない。方法を教えて'):
            with self.subTest(text=text):
                state = planner.observe(text, [])
                self.assertTrue(planner.plan(state, text).advice_allowed)
        text = '「アドバイスは要らん」という文の意味を説明して'
        self.assertNotEqual(planner.observe(text, []).user_dialogue_act, 'rejection')
        text = 'アドバイスはいらないわけじゃない'
        state = planner.observe(text, [])
        self.assertNotIn(state.user_dialogue_act, ('rejection', 'correction'))
        self.assertFalse(planner.plan(state, text).advice_allowed)
        text = '手順を教えて。今は助言いらない'
        self.assertFalse(planner.plan(planner.observe(text, []), text).advice_allowed)
        text = '手順教えて。でも今はいらない'
        self.assertFalse(planner.plan(planner.observe(text, []), text).advice_allowed)

    def test_separate_advice_request_is_allowed_after_question_rejected(self):
        adapter = FakeModelAdapter(['どこに行った？', 'ごめん。手順は一番目に確認する。'])
        chat = ChatSession(adapter)
        try:
            chat.turn('ただいま')
            chat.turn('質問はいらない。手順は教えて')
            spec = chat.alignment_trace['response_spec']
            self.assertTrue(spec['advice_allowed'])
            self.assertTrue(spec['acknowledge_misalignment'])
        finally:
            chat.close()

    def test_two_meta_leaks_report_deterministic_failure(self):
        leak = '修正後、以下が適切な返答です：おかえり。'
        chat = ChatSession(FakeModelAdapter([leak, leak]), prompt_mode='character-jp-repair')
        try:
            self.assertEqual(chat.turn('ただいま'), 'ごめん、返事がうまくまとまらなかった。')
            self.assertEqual(chat.core.provenance.last['fallback'], 'candidates_integrity_failure')
            self.assertIn('固定の失敗通知', chat.turn('その情報はどこから'))
        finally:
            chat.close()
    def test_mixed_meta_leak_cannot_win_over_clean_retry(self):
        adapter = FakeModelAdapter(['お疲れさamasensor修正後、以下が適切な返答です：ん、おかえり。どうだった？', 'おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-jp-repair')
        try:
            self.assertEqual(chat.turn('よお、やっと帰ってきた'), 'おかえり。')
            self.assertTrue(chat.last_response_meta['regenerated'])
        finally:
            chat.close()

    def test_explicit_edit_request_and_quotation_are_not_leaks(self):
        from companion_core.style import StyleValidator
        v = StyleValidator()
        self.assertEqual(v.instruction_leaks('修正後、以下が適切な返答です。', 'この文章を修正して'), [])
        self.assertEqual(v.instruction_leaks('「修正後、以下が適切な返答です」は引用。', 'この引用を説明して'), [])
    def test_experimental_low_risk_policy_violation_gets_one_retry(self):
        adapter = FakeModelAdapter(['おかえり。どうだった？', 'おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-jp-repair')
        try:
            self.assertEqual(chat.turn('おはよう'), 'おかえり。')
            self.assertEqual(len(adapter.requests), 2)
            self.assertIn('架空の未承認の口調例', adapter.requests[0][0]['content'])
            self.assertEqual(chat.alignment_trace['conversation_state']['risk_escalation'], 'experimental_policy_retry')
        finally:
            chat.close()
    def test_two_corrupt_outputs_use_explicit_cpu_failure_and_provenance(self):
        adapter = FakeModelAdapter(['不要继续。', '好久不见。'])
        chat = ChatSession(adapter, prompt_mode='character-repair')
        try:
            result = chat.turn('眠い')
            self.assertEqual(result, 'ごめん、返事がうまくまとまらなかった。')
            self.assertTrue(chat.last_response_meta['quality_fallback'])
            self.assertTrue(chat.last_response_meta['cpu'])
            self.assertEqual(chat.core.provenance.last['fallback'], 'both_candidates_language_mixing')
            self.assertFalse(chat.core.provenance.last['generated'])
            self.assertIn('固定の失敗通知', chat.turn('その情報はどこから'))
        finally:
            chat.close()
    def test_retry_preserves_original_roles_and_excludes_corrupt_draft(self):
        adapter = FakeModelAdapter(['おかえり。', '不要继续。', '眠いんだな。'])
        chat = ChatSession(adapter, prompt_mode='character-repair')
        try:
            chat.turn('ただいま')
            self.assertEqual(chat.turn('眠い'), '眠いんだな。')
            first, retry = adapter.requests[-2:]
            self.assertEqual(first[1:], retry[1:])
            self.assertNotIn('不要继续', str(retry))
            self.assertTrue(chat.last_response_meta['regenerated'])
        finally:
            chat.close()
