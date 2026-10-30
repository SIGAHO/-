"""Observed live failures: CPU control regressions, not model quality certification."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter


class LiveDialogueRegressions(unittest.TestCase):
    def test_praise_refusal_is_feedback_and_blocks_praise(self):
        chat = ChatSession(FakeModelAdapter(['参加したんだね。', 'ごめん、褒める話にした。']))
        self.addCleanup(chat.close)
        chat.turn('大会終わった')
        chat.turn('そこは褒めなくていい')
        self.assertEqual(chat.planned_state.reaction_to_previous, 'rejected')
        self.assertEqual(chat.planned_state.explicit_feedback, 'rejection')
        self.assertFalse(chat.planned_spec.praise_allowed)
        self.assertTrue(chat.planned_spec.acknowledge_misalignment)
        self.assertEqual(chat.alignment_trace['feedback_candidate_status']['status'], 'pending_human_review')

    def test_role_correction_is_not_treated_as_neutral_sharing(self):
        chat = ChatSession(FakeModelAdapter(['運営なんだね。', 'ごめん、客としての参加だね。']))
        self.addCleanup(chat.close)
        chat.turn('明日はイベント')
        chat.turn('運営じゃない。客として参加する')
        self.assertEqual(chat.planned_state.reaction_to_previous, 'corrected')
        self.assertIsNotNone(chat.planned_spec.target_reference)
        self.assertFalse(chat.planned_spec.advice_allowed)

    def test_experimental_examples_do_not_enter_memory_or_events(self):
        chat = ChatSession(FakeModelAdapter(['眠いんだね。']), prompt_mode='direct')
        self.addCleanup(chat.close)
        chat.turn('眠い')
        user_events = [e.payload['text'] for e in chat.core.events.events if e.kind == 'user_input']
        self.assertEqual(user_events, ['眠い'])
        self.assertFalse(any('電車が来なくて' in m.text for m in chat.core.memory.items))
        self.assertIn('fictional unapproved', chat.adapter.requests[0][0]['content'])

    def test_default_prompt_and_real_user_role_unchanged(self):
        chat = ChatSession(FakeModelAdapter(['眠いんだね。']))
        self.addCleanup(chat.close)
        chat.turn('眠い')
        self.assertEqual(chat.prompts.mode, 'legacy')
        self.assertEqual(chat.adapter.requests[0][-1], {'role': 'user', 'content': '眠い'})
        cpu = json.loads(chat.adapter.requests[0][0]['content'].split('CPU_CONTEXT\n')[1])
        self.assertIn('response_spec', cpu)


if __name__ == '__main__':
    unittest.main()
