"""Permanent multi-turn engineering hypotheses, not trusted training answers."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.alignment import PolicyPlanner, PolicyVerifier
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter, ModelError
from companion_core.models import Event, SourceType
from companion_core.preferences import PreferenceStore, group_split, validate


def events_for(case):
    return [Event('user_input' if role == 'user' else 'assistant_output', {'text': text},
                  SourceType.USER_STATEMENT if role == 'user' else SourceType.ASSISTANT_GENERATED,
                  id=f'{case["id"]}:{i}') for i, (role, text) in enumerate(case['history'] + [['user', case['user']]])]


def evaluate_case(case):
    planner = PolicyPlanner()
    events = events_for(case)
    state = planner.observe(case['user'], events, case.get('intent', 'casual_chat'))
    spec = planner.plan(state, case['user'], case.get('intent', 'casual_chat'))
    verifier = PolicyVerifier()
    return state, spec, verifier.verify(case['good'], spec, state, case['user']), verifier.verify(case['bad'], spec, state, case['user'])


class PermanentPolicySuite(unittest.TestCase):
    pass


CASES = [json.loads(line) for line in (ROOT / 'tests/fixtures/conversation-policy-v1.jsonl').read_text(encoding='utf-8').splitlines()]


def make_case_test(case):
    def test(self):
        state, spec, good, bad = evaluate_case(case)
        for name, expected in case['state'].items():
            self.assertEqual(getattr(state, name), expected, name)
        for name, expected in case['spec'].items():
            self.assertEqual(getattr(spec, name), expected, name)
        self.assertTrue(good['adherent'], good)
        self.assertIn(case['bad_issue'], bad['issues'])
        if case.get('reference'):
            self.assertEqual(state.reference_target['turn_id'], events_for(case)[-2].id)
            self.assertLessEqual(len(state.reference_target['context_turn_ids']), 6)
    return test


for case in CASES:
    setattr(PermanentPolicySuite, 'test_' + case['id'], make_case_test(case))


class AlignmentIntegrationTests(unittest.TestCase):
    def session(self, replies, path=None):
        session = ChatSession(FakeModelAdapter(replies), path)
        self.addCleanup(session.close)
        return session

    def test_medium_repair_rank_and_prompt_control(self):
        chat = self.session(['寝た方がいいよ。', '眠気きてるな。'])
        self.assertEqual(chat.turn('眠い'), '眠気きてるな。')
        self.assertEqual(len(chat.adapter.requests), 2)
        trace = chat.status()['conversation_alignment']
        self.assertFalse(trace['response_spec']['advice_allowed'])
        self.assertTrue(trace['verifier_result']['adherent'])
        self.assertEqual(trace['verifier_result']['candidate_count'], 2)
        self.assertIn('response_spec', chat.adapter.requests[0][0]['content'])

    def test_low_risk_one_policy_candidate(self):
        chat = self.session(['今日も頑張ろう！'])
        self.assertEqual(chat.turn('おはよう'), '今日も頑張ろう！')
        self.assertEqual(len(chat.adapter.requests), 1)
        self.assertFalse(chat.alignment_trace['verifier_result']['adherent'])
        self.assertTrue(chat.last_response_meta['fail_open'])

    def test_output_language_problem_escalates_risk_before_second_candidate(self):
        chat = self.session(['你今天感觉怎么样。', 'おはよう。'])
        chat.turn('おはよう')
        self.assertEqual(chat.alignment_trace['conversation_state']['response_risk'], 'medium')
        self.assertEqual(chat.alignment_trace['verifier_result']['candidate_count'], 2)

    def test_wake_and_informal_greetings_suppress_auxiliary_old_topic(self):
        for text in ('よお！', '起きたよ'):
            chat = self.session(['そうか。'] * 7)
            chat.turn('望遠鏡の計画')
            chat.turn(text)
            cpu = json.loads(chat.adapter.requests[-1][0]['content'].split('CPU_CONTEXT\n')[1])
            self.assertIsNone(cpu['topic'])
            self.assertEqual(cpu['memory'], [])
            self.assertEqual(cpu['session_recall'], [])
            self.assertIn('望遠鏡の計画', [m['content'] for m in chat.adapter.requests[-1][1:-1]])

    def test_fail_open_and_one_retry_total(self):
        chat = self.session(['早く寝よう！', '寝た方がいいよ。'])
        self.assertTrue(chat.turn('眠い'))
        self.assertEqual(len(chat.adapter.requests), 2)
        self.assertTrue(chat.last_response_meta['fail_open'])
        self.assertFalse(chat.alignment_trace['verifier_result']['adherent'])

    def test_repair_failure_does_not_replace_valid_original(self):
        chat = self.session(['早く寝よう！'])
        with patch.object(chat.adapter, 'generate', side_effect=['早く寝よう！', ModelError('timeout')]):
            # Existing generation failure contract remains distinct from a
            # policy violation: a failed transport is not a fabricated reply.
            with self.assertRaises(ModelError):
                chat.turn('眠い')
        self.assertIsNone(chat.core.last_assistant)

    def test_reaction_chain_and_ambiguous_not_approved(self):
        chat = self.session(['いい経験になる。', 'ごめん、受け取り方がずれた。', 'うん。'])
        chat.turn('明日はイベントだ')
        chat.turn('そういうことじゃない')
        rows = chat.fio.experiences.all()
        responses = [json.loads(r['body']) for r in rows if r['kind'] == 'assistant_response']
        reactions = [json.loads(r['body']) for r in rows if r['kind'] == 'next_user_reaction']
        self.assertEqual(reactions[0]['causation_id'], responses[0]['turn_id'] + ':assistant_response')
        self.assertEqual(reactions[0]['explicit_feedback'], 'rejection')
        self.assertEqual(chat.fio.preferences.counts()['candidates'], 1)
        chat.turn('ああ')
        self.assertEqual(chat.fio.preferences.counts()['candidates'], 1)
        self.assertEqual(chat.fio.preferences.counts()['human_approved'], 0)
        self.assertEqual(chat.fio.preferences.trusted(), [])

    def test_explicit_approval_is_only_a_candidate(self):
        chat = self.session(['うん。', 'うん。'])
        chat.turn('おはよう')
        chat.turn('今の返答がいい')
        candidate = next(iter(chat.fio.preferences.records.values()))
        self.assertEqual(candidate['chosen'], 'うん。')
        self.assertFalse(candidate['human_approved'])
        self.assertFalse(candidate['teacher_generated'])

    def test_third_party_report_is_not_feedback_on_assistant(self):
        from companion_core.chat import ChatSession
        from companion_core.model_adapter import FakeModelAdapter
        from companion_core.alignment import PolicyPlanner
        planner = PolicyPlanner()
        self.assertNotEqual(planner.observe('友達は質問しないでと言っていた。', []).user_dialogue_act, 'rejection')
        self.assertEqual(planner.observe('友達は質問しないでと言っていた。私には質問しないで。', []).user_dialogue_act, 'rejection')
        chat = ChatSession(FakeModelAdapter(['そうなんだな。', 'そうか。']))
        try:
            chat.turn('今日は図書館へ行った')
            chat.turn('友達は質問しないでと言っていた。')
            self.assertNotEqual(chat.alignment_trace['conversation_state']['reaction_to_previous'], 'rejected')
            self.assertEqual(chat.fio.preferences.records, {})
        finally:
            chat.close()

    def test_outbox_recovery_is_idempotent_and_memory_boundary_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(['うん。', 'ごめん、ずれてた。']), path)
            chat.turn('今日の予定はイベントだ')
            chat.turn('そういうことじゃない')
            counts = chat.fio.preferences.counts()
            before = chat.fio.experiences.all()
            chat.fio.recover(chat.core.events.events)
            self.assertEqual(chat.fio.experiences.all(), before)
            chat.close()
            restored = ChatSession(FakeModelAdapter(), path)
            try:
                self.assertEqual(restored.fio.preferences.counts(), counts)
                self.assertEqual(restored.fio.experiences.all(), before)
                self.assertFalse(any(r.source == SourceType.ASSISTANT_GENERATED for r in restored.core.memory.items))
                self.assertFalse(any(r.source == SourceType.ASSISTANT_GENERATED for r in restored.core.state.active.values()))
            finally:
                restored.close()

    def test_crash_between_raw_feedback_and_preparation_recovers_candidate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            chat = ChatSession(FakeModelAdapter(['そうか。']), path)
            chat.turn('明日はイベントだ')
            chat.core.handle('そういうことじゃない')
            chat.close()
            restored = ChatSession(FakeModelAdapter(), path)
            try:
                self.assertEqual(restored.fio.preferences.counts()['candidates'], 1)
                self.assertEqual(len(restored.fio.recorder.records), 1)
                before = restored.fio.experiences.all()
                restored.fio.recover(restored.core.events.events)
                self.assertEqual(restored.fio.experiences.all(), before)
                self.assertEqual(restored.fio.preferences.trusted(), [])
            finally:
                restored.close()

    def test_greeting_and_explicit_recall_preserve_fio(self):
        chat = self.session(['そうか。'] * 10)
        chat.turn('古い望遠鏡の計画')
        for i in range(5):
            chat.turn(f'別の報告{i}')
        chat.turn('おはよう')
        self.assertFalse(chat.alignment_trace['recall_source']['session_recall'])
        self.assertNotIn('古い望遠鏡', chat.adapter.requests[-1][0]['content'])
        chat.turn('前に望遠鏡の話したよな？')
        self.assertTrue(chat.fio.pending is None)
        self.assertTrue(chat.fio.recorder.records[-1]['user'].startswith('前に'))
        self.assertTrue(json.loads(chat.adapter.requests[-1][0]['content'].split('CPU_CONTEXT\n')[1])['session_recall'])

    def test_failure_recall_reinforces_without_truth_admission(self):
        chat = self.session(['そうか。', 'ごめん、ずれてた。', 'ごめん、ずれてた。'])
        chat.turn('明日はイベントだ')
        chat.turn('そういうことじゃない')
        chat.turn('そういうことじゃない')
        self.assertTrue(chat.alignment_trace['recall_source']['experiences'])
        self.assertTrue(any(r['references_count'] for r in chat.fio.experiences.all()))


class PreferenceTests(unittest.TestCase):
    def record(self, **updates):
        session = next(str(i) for i in range(100) if group_split(str(i)) == 'train')
        return {'schema_version': 1, 'id': 'candidate1', 'context': [], 'raw_turn_ids': ['turn1'],
                'response_spec': {}, 'chosen': '返答', 'rejected': None, 'source_type': 'real_user_feedback',
                'teacher_model': None, 'teacher_generated': False, 'human_approved': False,
                'provenance': {}, 'session_id': session, 'turn_id': 'turn1', 'split': 'train', **updates}

    def test_approval_hash_bound_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(directory)
            row = self.record()
            store.append(row)
            self.assertEqual(store.trusted(), [])
            store.approve(row['id'], reviewer='human-test-operator')
            self.assertTrue(PreferenceStore(directory).trusted()[0]['human_approved'])
            self.assertFalse(store.append(row))
            with self.assertRaises(ValueError):
                store.append({**row, 'chosen': '別の返答'})

    def test_independent_writer_conflict_preserves_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            one, two = PreferenceStore(directory), PreferenceStore(directory)
            one.append(self.record())
            raw = (Path(directory) / 'candidates.jsonl').read_bytes()
            with self.assertRaises(OSError):
                two.append(self.record(id='second'))
            self.assertEqual((Path(directory) / 'candidates.jsonl').read_bytes(), raw)

    def test_partial_ledger_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'candidates.jsonl'
            file.write_bytes(b'{"schema_version":1')
            with self.assertRaises(ValueError):
                PreferenceStore(directory)
            self.assertEqual(file.read_bytes(), b'{"schema_version":1')

    def test_claimed_approval_is_not_enough(self):
        store = PreferenceStore()
        store.append(self.record(human_approved=True))
        self.assertEqual(store.trusted(), [])

    def test_reject_target_teacher_and_alias(self):
        for model in ('qwen2.5:14b', 'Qwen2.5:14b-instruct', 'qwen2.5:32b', 'Qwen/Qwen2.5-14B-Instruct'):
            with self.assertRaises(ValueError):
                validate(self.record(source_type='external_teacher_candidate', teacher_model=model, teacher_generated=True))

    def test_external_teacher_is_not_trusted(self):
        row = self.record(source_type='external_teacher_candidate', teacher_model='independent-model', teacher_generated=True)
        store = PreferenceStore()
        store.append(row)
        self.assertEqual(store.counts()['teacher_generated'], 1)
        self.assertEqual(store.trusted(), [])

    def test_group_split_no_leak_and_no_blind_export(self):
        store = PreferenceStore()
        blind = next(str(i) for i in range(100) if group_split(str(i)) == 'blind_holdout')
        row = self.record(session_id=blind, split='blind_holdout')
        store.append(row)
        store.approve(row['id'], reviewer='human-test-operator')
        self.assertEqual(store.trusted(), [])
        with self.assertRaises(ValueError):
            store.trusted('blind_holdout')
        with self.assertRaises(ValueError):
            validate({**row, 'split': 'train'})

    def test_no_empty_or_invalid_sources(self):
        for values in ({'chosen': None}, {'source_type': 'model_judge'}, {'human_approved': 'yes'},
                       {'teacher_generated': True}, {'raw_turn_ids': 'bad'}):
            with self.assertRaises(ValueError):
                validate(self.record(**values))


if __name__ == '__main__':
    unittest.main()
