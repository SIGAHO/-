"""Structural language regressions from user-observed outputs, not training."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter
from companion_core.style import StyleValidator


class LanguageStyleTests(unittest.TestCase):
    def session(self, replies):
        chat = ChatSession(FakeModelAdapter(replies))
        self.addCleanup(chat.close)
        return chat

    def test_mixed_chinese_user_observation_triggers_single_rewrite(self):
        chat = self.session(['おはようございます！元気だったか？今日も一日、一緒に頑張ろうね。什么事需要帮助的吗？哦，看来你刚才是在做梦。感觉怎么样？',
                             '目が覚めたんだね。'])
        self.assertEqual(chat.turn('めがさめた！！'), '目が覚めたんだね。')
        self.assertEqual(len(chat.adapter.requests), 2)
        self.assertIn('language_mixing', chat.last_response_meta['issues'])

    def test_malformed_inflection_triggers_rewrite(self):
        chat = self.session(['お疲れさamasますん。早寝して明日に備えよう。', '眠いんだね。'])
        self.assertEqual(chat.turn('眠い！'), '眠いんだね。')
        self.assertIn('language_mixing', chat.last_response_meta['issues'])

    def test_style_rewrite_cannot_introduce_foreign_prose(self):
        original = '起きたんですね。ゆっくりしてください。'
        chat = self.session([original, '什么事需要帮助的吗？'])
        self.assertEqual(chat.turn('起きた'), original)
        self.assertTrue(chat.last_response_meta['fail_open'])
        self.assertNotIn('language_mixing', chat.last_response_meta['remaining_issues'])

    def test_repeated_language_problem_never_stops_or_deletes_body(self):
        original = '目が覚めたんだね。什么事需要帮助的吗？'
        chat = self.session([original, original])
        self.assertEqual(chat.turn('起きた'), original)
        self.assertTrue(chat.last_response_meta['fail_open'])
        self.assertEqual(len(chat.adapter.requests), 2)
        self.assertEqual(chat.core.last_assistant, original)

    def test_quotes_code_urls_and_technical_terms_preserved(self):
        for text in ('PythonとAPIでソフトを作る。', 'これはpythonです。', '「什么事需要帮助的吗？」は引用。',
                     '```python\nprint("你好吗")\n```', '`asyncかな`を変数にする。',
                     'https://example.com/hello/world', '明日休業。東京大学。需要増加。'):
            with self.subTest(text=text):
                self.assertEqual(StyleValidator().language_issues(text), [])

    def test_explicit_other_language_request_is_preserved(self):
        text = '你好，很高兴见到你。'
        chat = self.session([text])
        self.assertEqual(chat.turn('中国語で挨拶して'), text)
        self.assertEqual(len(chat.adapter.requests), 1)

    def test_english_prose_detected_but_short_hmm_does_not_switch_language(self):
        chat = self.session(['You should rest now.', '眠いなら少し休もう。'])
        self.assertEqual(chat.turn('hmm'), '眠いなら少し休もう。')
        self.assertIn('language_mixing', chat.last_response_meta['issues'])

    def test_japanese_translation_target_does_not_disable_check(self):
        self.assertEqual(StyleValidator().language_issues('你今天感觉怎么样？', '中国語を日本語に翻訳して'), ['language_mixing'])

    def test_generation_and_rewrite_both_instruct_natural_japanese(self):
        chat = self.session(['確認します。準備します。', 'わかった。'])
        chat.turn('眠い！')
        for request in chat.adapter.requests:
            self.assertIn('自然な日本語', request[0]['content'])
        self.assertIn('履歴の言語混在や壊れた語尾をまねしない', chat.adapter.requests[0][0]['content'])


if __name__ == '__main__':
    unittest.main()
