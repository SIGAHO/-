"""Regression coverage for Japanese Production conversation quality guards."""

import unittest

import breaktail_v02 as tail


class LanguageQualityTests(unittest.TestCase):
    def test_japanese_chat_rejects_cyrillic_leak(self):
        reply, changes = tail.phase7_postprocess_reply(
            [], "堅苦しいしゃべり方やめてほしい",
            "分かった、タメ口で話すよ。どうした чего сказать дальше?"
        )
        self.assertEqual(reply, "分かった、タメ口で話すよ。どうした")
        self.assertIn("removed_unrequested_foreign_script", changes)

    def test_japanese_chat_rejects_chinese_fragment(self):
        reply, changes = tail.phase7_postprocess_reply([], "今日はいい日", "うん、今日はいい日だね。我们继续聊")
        self.assertNotRegex(reply, r"[你我他她们这那吗没别让给还为后过从对发觉应开关啥请续啊么说吧聊呦嗯于观习饭]")
        self.assertIn("removed_unrequested_chinese", changes)

    def test_arabic_source_is_recognized_without_blocking_japanese_translation(self):
        source = "لقد فعلها هذا اللعين! حان وقت الانتقام. 翻訳して"
        self.assertEqual(tail.translation_source_script(source), "Arabic")
        self.assertIsNone(tail.untranslated_transliteration_reply(source))
        messages = tail.build_reply_messages([], source, None)
        self.assertIn("source_script=Arabic", messages[0]["content"])
        reply, changes = tail.phase7_postprocess_reply([], source, "阿拉伯語の文だよ。原文は「لقد فعلها」だね。")
        self.assertIn("アラビア語", reply)
        self.assertNotIn("阿拉伯語", reply)
        self.assertIn("normalized_arabic_language_name", changes)
        self.assertNotIn("removed_unrequested_foreign_script", changes)

    def test_unlabeled_katakana_transliteration_never_guesses_language(self):
        text = "ラカド・ファアラハー・ハーザ・アッライーン！ 翻訳どうぞｗ"
        reply = tail.untranslated_transliteration_reply(text)
        self.assertIsNotNone(reply)
        self.assertIn("元の言語", reply)
        self.assertNotIn("インドネシア", reply)

    def test_translation_drops_generic_closing_question(self):
        source = "«لقد فعلها هذا اللعين! 翻訳どうぞｗ»"
        reply, changes = tail.phase7_postprocess_reply(
            [], source,
            "その文はアラビア語だよ。『この野郎がやった』という意味。\n\n面白い表現ですね、何か特定の作品や状況から引用ですか？"
        )
        self.assertEqual(reply, "その文はアラビア語だよ。『この野郎がやった』という意味。")
        self.assertIn("removed_generic_followup", changes)

    def test_normal_chat_keeps_casual_japanese(self):
        reply, changes = tail.phase7_postprocess_reply([], "今日はいい日", "それはいいじゃん。")
        self.assertEqual(reply, "それはいいじゃん。")
        self.assertEqual(changes, [])

    def test_japanese_chat_removes_embedded_english_and_generic_question(self):
        reply, changes = tail.phase7_postprocess_reply(
            [], "堅苦しいしゃべり方やめてほしい",
            "分かった、もっと自然な感じで話すね。何か specific なことは聞きたい？"
        )
        self.assertEqual(reply, "分かった、もっと自然な感じで話すね。")
        self.assertIn("removed_generic_followup", changes)

    def test_current_user_code_or_log_foreign_text_is_not_stripped(self):
        user = "このログの `Ошибка` って何？"
        reply, changes = tail.phase7_postprocess_reply([], user, "ログにある `Ошибка` はエラーって意味だよ。")
        self.assertIn("Ошибка", reply)
        self.assertNotIn("removed_unrequested_foreign_script", changes)


if __name__ == "__main__":
    unittest.main()
