import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import breaktail_v02 as tail
from breaktail_self import SelfRuntime, build_self_context, ground_self_reply


HTML = '''<!DOCTYPE html>
<html lang="ja"><head><style>body { color: red; }</style></head>
<body><p id="score">0</p><script>
let score = 0;
function clickScore() {
  score++;
  document.getElementById('score').textContent = `スコア: ${score}`;
}
</script></body></html>'''


class CodePreservationTests(unittest.TestCase):
    def clean(self, text):
        return tail.phase7_postprocess_reply([], 'コードを書いて', text)[0]

    def test_fenced_html_exact(self):
        code = '```html\n' + HTML + '\n```\n'
        self.assertEqual(self.clean(code), code)

    def test_script_tags_exact(self):
        code = '<script>let score = 0;</script>'
        self.assertEqual(self.clean(code), code)

    def test_template_literal_exact(self):
        code = '```js\nconst label = `Score: ${score}`;\n```'
        self.assertEqual(self.clean(code), code)

    def test_prose_guard_still_runs(self):
        code = '```js\nlet score = 0;\n```\n'
        output = self.clean('いいね。我们继续聊\n' + code + 'いいね。unwantedword')
        self.assertIn(code, output)
        self.assertNotIn('我们', output)
        self.assertNotIn('unwantedword', output)

    def test_json_exact(self):
        code = '{\n "message": "Ошибка, 你好", "score": "${score}"\n}'
        self.assertEqual(self.clean(code), code)

    def test_xml_exact(self):
        code = '<?xml version="1.0"?><root><message>你好</message></root>'
        self.assertEqual(self.clean(code), code)

    def test_log_exact(self):
        code = '[ERROR] Ошибка: request_id=${score}, retry=false\n'
        self.assertEqual(self.clean(code), code)

    def test_unfenced_html_then_prose(self):
        output = self.clean(HTML + '\n\nいいね。unwantedword')
        self.assertTrue(output.startswith(HTML))
        self.assertNotIn('unwantedword', output)

    def test_incomplete_fence_kept(self):
        code = '```js\nconst score = "你好";\n'
        self.assertEqual(self.clean(code), code)

    def test_inline_and_tilde_fences(self):
        for code in ['`document.querySelector("#score")`', '~~~js\nlet nice = "你好";\n~~~']:
            self.assertEqual(self.clean(code), code)

    def test_grounding_preserves_code_claim_strings(self):
        code = '```js\nconst s = "最新情報では、修正しました";\n```'
        self.assertEqual(ground_self_reply('コード書いて', code, build_self_context())['reply'], code)


class TimeAndStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2031, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=9)))
        with patch('breaktail_self.datetime') as clock:
            clock.now.return_value.astimezone.return_value = self.now
            self.context = build_self_context()

    def reply(self, user, draft='現在は2023年。時計やカレンダーAPIが必要です。'):
        return ground_self_reply(user, draft, self.context)['reply']

    def test_current_year(self):
        self.assertEqual(self.reply('今年って何年？'), '今年は2031年だよ。')

    def test_current_date(self):
        self.assertIn('2031年1月2日', self.reply('今日の日付は？'))

    def test_current_time(self):
        self.assertIn('3時04分（UTC+09:00）', self.reply('今何時？'))

    def test_combined_date_time(self):
        answer = self.reply('じゃあ今日は何月何日何時何分？')
        self.assertIn('2031年1月2日', answer)
        self.assertIn('3時04分', answer)

    def test_stale_year_corrected(self):
        self.assertNotIn('2023', self.reply('現在何年？', '2023年'))

    def test_clock_api_unnecessary(self):
        self.assertNotIn('API', self.reply('今何時？'))
        self.assertIn('APIは不要', self.context['prompt'])

    def test_clock_refreshes(self):
        self.assertNotEqual(build_self_context()['facts']['current_datetime_iso'], self.context['facts']['current_datetime_iso'])
        self.assertEqual(self.context['facts']['timezone_offset'], '+09:00')

    def test_time_code_and_translation_not_overridden(self):
        for user in ['今年が何年か表示するコードを書いて', '「今年って何年？」を翻訳して', '今日のニュースは？', '今年何年生になる？']:
            self.assertEqual(self.reply(user, 'モデルの回答'), 'モデルの回答')

    def test_latest_info_without_search(self):
        for phrase in ['最新の情報では', '最新情報では']:
            self.assertNotIn(phrase, self.reply('2026だぞ', phrase + '2026年です。'))

    def test_persistence_claim_without_result(self):
        self.assertNotIn('修正しました', self.reply('2026だぞ', '修正しました。'))

    def test_successful_search_preserved(self):
        ctx = build_self_context(SelfRuntime(web_search_available=True, search_state='success', search_observation='result'))
        self.assertEqual(ground_self_reply('結果は？', '最新情報ではAだよ。', ctx)['reply'], '最新情報ではAだよ。')

    def test_vision_not_connected(self):
        self.assertEqual(self.context['capabilities']['vision_state'], 'not_connected')
        self.assertIn('まだ接続されていない', self.reply('おまえ見れるようにしたくね？おれのPC画面', '今回は働いてない'))

    def test_vision_temporary_failure(self):
        ctx = build_self_context(SelfRuntime(vision_connected=True, vision_failed=True))
        self.assertEqual(ctx['capabilities']['vision_state'], 'temporary_failed')
        answer = ground_self_reply('画面見える？', '見える', ctx)['reply']
        self.assertIn('一時的に失敗', answer)
        self.assertNotIn('まだ接続されていない', answer)

    def test_vision_success_and_available(self):
        self.assertEqual(build_self_context(SelfRuntime(vision_connected=True))['capabilities']['vision_state'], 'available')
        ctx = build_self_context(SelfRuntime(vision_succeeded=True, vision_observation='赤い画面'))
        self.assertEqual(ctx['capabilities']['vision_state'], 'success')
        self.assertIn('赤い画面', ground_self_reply('画面見える？', '不明', ctx)['reply'])


if __name__ == '__main__':
    unittest.main()
