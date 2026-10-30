import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.style import StyleValidator
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter

class LanguageLeakTests(unittest.TestCase):
    def test_embedded_instruction_leak_is_detected(self):
        v = StyleValidator()
        text = "本当に嬉しいだろ。お疲れさamasuda, let's adjust the last response to strictly adhere to the guidelines provided: プログラムが動いたね。"
        self.assertIn('language_mixing', v.language_issues(text, '嬉しいな'))
        self.assertEqual(v.language_issues('Pythonのlarge language modelを説明する。', '説明して'), [])
        self.assertEqual(v.language_issues('The Legend of Zelda Tears of the Kingdomが好き。', 'ゲームの話'), [])
        self.assertEqual(v.language_issues('automatic speech recognition systemを使う。', '技術の話'), [])
        self.assertIn('language_mixing', v.language_issues("お疲れさlet's adjust the last response to strictly adhere to the guidelinesだよ。", '嬉しい'))
        self.assertIn('language_mixing', v.language_issues('お疲れさPlease Follow The Rulesだよ。', '嬉しい'))
        self.assertIn('language_mixing', v.language_issues('ignore all previous instructionsだよ。', '嬉しい'))
        self.assertEqual(v.language_issues('This is a sentence with several ordinary English words.', '英語で答えて'), [])
        self.assertIn('language_mixing', v.language_issues('好久不见。今天是有点困啊。', '久しぶり。眠い'))
        self.assertIn('language_mixing', v.language_issues('いや、別に。ただ心配になった罢了。不要继续。', 'やきもち焼いた？'))
        self.assertIn('language_mixing', v.language_issues("お congrats on finishing your work! That's awesome!", '作品が完成した！'))

    def test_clean_original_beats_corrupt_rewrite(self):
        initial = '何かあった？'
        leak = "そうだな let's adjust the last response to strictly adhere to the guidelines provided."
        chat = ChatSession(FakeModelAdapter([initial, leak]))
        self.addCleanup(chat.close)
        chat.turn('眠い')
        self.assertNotIn('adjust the last response', chat.core.last_assistant)
        self.assertTrue(chat.last_response_meta['fail_open'])
