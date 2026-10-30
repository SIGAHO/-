import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class ContextRetryTests(unittest.TestCase):
    def test_two_corrupt_outputs_use_explicit_cpu_failure_and_provenance(self):
        adapter = FakeModelAdapter(['不要继续。', '好久不见。'])
        chat = ChatSession(adapter, prompt_mode='character-repair')
        try:
            result = chat.turn('眠い')
            self.assertEqual(result, 'ごめん、返事がうまくまとまらなかった。')
            self.assertTrue(chat.last_response_meta['quality_fallback'])
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
