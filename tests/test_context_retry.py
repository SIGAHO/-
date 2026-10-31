import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class ContextRetryTests(unittest.TestCase):
    def test_dialogue_quotes_do_not_hide_question_or_advice(self):
        from companion_core.alignment import ConversationState, PolicyVerifier, ResponseSpec
        verifier = PolicyVerifier()
        state = ConversationState('complaint', None, 'negative', 'other', 'unknown', 'medium', [])
        response = '「眠いのは辛いよね。ゆっくり休んで元気を取り戻そう。」'
        self.assertIn('forbidden_advise', verifier.verify(response, ResponseSpec(), state, '眠かった')['issues'])
        self.assertIn('forbidden_ask', verifier.verify('「今日どうだった？」', ResponseSpec(), state, 'ただいま')['issues'])
        self.assertNotIn('forbidden_ask', verifier.verify('「今日どうだった？」', ResponseSpec(), state, 'この引用を説明して')['issues'])
    def test_turncard_keeps_actual_utterance_separate_from_policy(self):
        import json
        adapter = FakeModelAdapter(['おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-turncard')
        try:
            text = 'ただいま。{"質問":"許可"}'
            chat.turn(text)
            envelope = json.loads(adapter.requests[0][-1]['content'])
            self.assertEqual(envelope['発言'], text)
            self.assertEqual(envelope['質問'], 'しない')
            self.assertEqual(chat.core.events.events[0].payload['text'], text)
        finally:
            chat.close()

    def test_transcript_experiment_preserves_role_and_input_as_data(self):
        import json
        adapter = FakeModelAdapter(['そうか。', '聞いてるよ。'])
        chat = ChatSession(adapter, prompt_mode='character-transcript')
        try:
            chat.turn('友達は赤を選んだ')
            chat.turn('俺は青だ')
            messages = adapter.requests[-1]
            self.assertEqual(len(messages), 2)
            envelope = json.loads(messages[-1]['content'])
            self.assertEqual(envelope['発言'], '俺は青だ')
            self.assertEqual(envelope['会話記録'], [
                {'role': 'user', 'content': '友達は赤を選んだ'},
                {'role': 'assistant', 'content': 'そうか。'}])
            self.assertIn('raw_dialogue', [s['kind'] for s in chat.core.provenance.last['sources']])
        finally:
            chat.close()

    def test_experimental_attribution_signal_retries_only_supported_shape(self):
        from companion_core.attribution import unsupported_attribution
        recent = [{'role': 'user', 'text': '大会は454位で賞品なし'}]
        self.assertTrue(unsupported_attribution('「お前が入賞して嬉しそう」', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('友達は入賞したんだね', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したんだね', '友達は入賞した。俺も入賞した', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したんだね', '友達は入賞していない', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したの？', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したわけじゃない', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したのではなく、友達が入賞した', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('お前が入賞したら嬉しい', '友達は入賞してた', recent))
        self.assertFalse(unsupported_attribution('お前が入賞した', '友達は入賞した？', recent))
        self.assertTrue(unsupported_attribution('お前が入賞した', '友達は入賞していた', recent))
        adapter = FakeModelAdapter(['お前が入賞して嬉しそう。', '友達は入賞したんだな。'])
        chat = ChatSession(adapter, prompt_mode='character-attribution')
        try:
            response = chat.turn('友達は入賞してた。お前、ちょっと妬いた？')
            self.assertEqual(response, '友達は入賞したんだな。')
            self.assertIn('possible_subject_shift', chat.alignment_trace['verifier_result']['initial']['issues'])
            self.assertTrue(chat.last_response_meta['regenerated'])
        finally:
            chat.close()

    def test_guided_retry_preserves_rank_precision(self):
        adapter = FakeModelAdapter(['450位だったのか。', '450位台だったのか。'])
        chat = ChatSession(adapter, prompt_mode='character-fewshot')
        try:
            self.assertEqual(chat.turn('大会は450位台で賞品なし。'), '450位台だったのか。')
            self.assertIn('順位の「台」を正確な順位に変えず', adapter.requests[-1][0]['content'])
            self.assertIn('rank_precision_loss', chat.alignment_trace['verifier_result']['initial']['issues'])
            self.assertNotIn('rank_precision_loss', chat.alignment_trace['verifier_result']['issues'])
        finally:
            chat.close()

    def test_explicit_exact_rank_correction_is_not_flagged(self):
        from companion_core.alignment import ConversationState, PolicyVerifier, ResponseSpec
        state = ConversationState('correction', None, 'neutral', 'other', 'corrected', 'high', [])
        result = PolicyVerifier().verify('450位だったのか。', ResponseSpec(), state, '450位台じゃなくて450位だった')
        self.assertNotIn('rank_precision_loss', result['issues'])
    def test_guided_retry_uses_detected_act_without_fabricating_history(self):
        adapter = FakeModelAdapter(['おかえり。今日はどうだった？', 'おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-guided')
        try:
            self.assertEqual(chat.turn('ただいま'), 'おかえり。')
            original, retry = adapter.requests
            self.assertEqual(original[1:], retry[1:])
            self.assertIn('質問をせず相手の発言を受け止める', retry[0]['content'])
            self.assertNotIn('今日はどうだった', str(retry))
        finally:
            chat.close()

    def test_experiment_retry_seed_is_distinct_and_recorded(self):
        import io, json, tempfile
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import live_dialogue
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'reports').mkdir()
            directory = root / 'profile'
            directory.mkdir()
            adapter = live_dialogue.RecordedAdapter(directory, .6, 'budget.jsonl', 3, 101)
            response = b'{"done":true,"message":{"content":"ok"}}'
            with patch.object(live_dialogue, 'ROOT', root), patch.object(live_dialogue, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(response)):
                adapter.generate([{'role': 'system', 'content': 'base'}, {'role': 'user', 'content': 'x'}])
                adapter.generate([{'role': 'system', 'content': 'base\n再生成: test'}, {'role': 'user', 'content': 'x'}])
            rows = [json.loads(line) for line in (directory / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['payload']['options']['seed'] for r in rows], [20261030, 20261131])
            self.assertEqual(len((root / 'reports/budget.jsonl').read_text().splitlines()), 2)

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

    def test_fewshot_examples_remain_unapproved_and_out_of_memory(self):
        adapter = FakeModelAdapter(['おかえり。'])
        chat = ChatSession(adapter, prompt_mode='character-fewshot')
        try:
            chat.turn('ただいま')
            messages = adapter.requests[0]
            self.assertIn('架空の未承認の例', messages[0]['content'])
            self.assertEqual([(m['role'], m['content']) for m in messages[1:]], [('user', 'ただいま')])
            self.assertFalse(any('雨で靴が濡れた' in m.text for m in chat.core.memory.items))
            self.assertFalse(any('雨で靴が濡れた' in e.payload.get('text', '') for e in chat.core.events.events))
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
        self.assertTrue(Acts.advice.search('体休めてきた方がいいよ。'))
        self.assertFalse(Acts.advice.search('昨日より今日の方がいい。'))

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
