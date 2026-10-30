import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.alignment import Acts, PolicyPlanner, PolicyVerifier
from companion_core.models import Event, SourceType

class CelebrationDetectionTests(unittest.TestCase):
    def test_polite_apology_acknowledges_a_misalignment(self):
        from dataclasses import replace
        user = '干渉はやめて'
        events = [Event('assistant_output', {'text': 'いつもそばにいて'}, SourceType.ASSISTANT_GENERATED),
                  Event('user_input', {'text': user}, SourceType.USER_STATEMENT)]
        planner = PolicyPlanner()
        state = planner.observe(user, events)
        spec = replace(planner.plan(state, user), acknowledge_misalignment=True)
        result = PolicyVerifier().verify('分かった、すみません。', spec, state, user)
        self.assertNotIn('missing_misalignment_acknowledgment', result['issues'])
        blamed = PolicyVerifier().verify('あなたが誤解したんだよ。', spec, state, user)
        self.assertIn('missing_misalignment_acknowledgment', blamed['issues'])
        self.assertIn('missing_misalignment_acknowledgment', PolicyVerifier().verify('誤解したのはあなたでしょ。', spec, state, user)['issues'])
        self.assertNotIn('missing_misalignment_acknowledgment', PolicyVerifier().verify('誤解した、ごめん。', spec, state, user)['issues'])

    def test_lively_completion_allows_celebration(self):
        user = 'やっとプログラムが動いたぞ！'
        events = [Event('user_input', {'text': user}, SourceType.USER_STATEMENT)]
        planner = PolicyPlanner()
        state = planner.observe(user, events)
        spec = planner.plan(state, user)
        self.assertEqual(state.user_dialogue_act, 'celebration')
        self.assertTrue(spec.praise_allowed)
        self.assertTrue(PolicyVerifier().verify('お、すごいな！', spec, state, user)['adherent'])

    def test_intensifier_is_not_automatically_praise(self):
        self.assertFalse(Acts.praise.search('すごく眠いんだね。'))
        self.assertTrue(Acts.praise.search('すごく上手だね。'))
        self.assertTrue(Acts.praise.search('すごいな！'))
