import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class ContextRetryTests(unittest.TestCase):
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
