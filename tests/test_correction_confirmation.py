"""Correction admission must preserve facts when no replacement is specified."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore, SourceType
from companion_core.correction import CorrectionEngine


class CorrectionConfirmationTests(unittest.TestCase):
    def test_negated_or_uncertain_definition_is_not_promoted(self):
        engine = CorrectionEngine()
        for tail in ('って意味ではない', 'って意味じゃない', 'という意味ではない',
                     'って意味かもしれない', 'って意味？', 'って意味ですか', 'って意味なの？', 'って意味なら'):
            with self.subTest(tail=tail):
                self.assertEqual(engine.detect('ルクルアっていうのは大会' + tail), [])
                self.assertEqual(engine.detect('赤じゃなくて青。ルクルアっていうのは大会' + tail), [])
        for tail in ('って意味', 'という意味だ', 'って話です'):
            self.assertEqual(engine.detect('ルクルアっていうのは大会' + tail)[0].new, '大会')
        self.assertEqual(engine.detect('ルクルアっていうのは大会って意味!')[0].new, '大会')

    def test_question_and_speculation_do_not_commit_corrections(self):
        engine = CorrectionEngine()
        for text in ('赤じゃなくて青？', '赤じゃなくて青?', '違う、青？', '違う、青?',
                     '赤じゃなくて青かもしれない', '違う、青かも'):
            with self.subTest(text=text):
                self.assertEqual(engine.detect(text), [])
        self.assertEqual(engine.detect('赤じゃなくて青')[0].new, '青')

    def test_quoted_and_polite_uncertainty_are_not_confirmed(self):
        engine = CorrectionEngine()
        for text in ('赤じゃなく青かもしれません。', '赤じゃなく青だと思います。', '赤じゃなく青らしい。', '赤じゃなく青かもしれませんよ。', '赤じゃなく青だと思いますね。', '赤じゃなく「青」と友達が言った。',
                     '違う、青かもしれません。', '「赤じゃなく青」と言ったのは友達だ。',
                     '「違う、青」と友達が言った。', '赤じゃなく青。『緑じゃなく黄色』と友達が言った。'):
            with self.subTest(text=text):
                self.assertEqual(engine.detect(text), [])
        self.assertEqual(engine.detect('「赤」じゃなく「青」')[0].new, '「青」')

    def test_lexical_adjective_is_not_conjectural_auxiliary(self):
        engine = CorrectionEngine()
        for adjective in ('素晴らしい', '男らしい', '新しい'):
            with self.subTest(adjective=adjective):
                self.assertEqual(engine.detect('普通じゃなく' + adjective)[0].new, adjective)
                self.assertEqual(engine.detect('普通っていうのは' + adjective + 'って意味')[0].new, adjective)
        for text in ('普通じゃなく青らしい', '普通じゃなく青らしいです', '普通じゃなく明日は晴れらしい'):
            self.assertEqual(engine.detect(text), [])

    def test_quoted_value_punctuation_is_preserved(self):
        engine = CorrectionEngine()
        for punctuation in (',', '!', '、', '！'):
            with self.subTest(punctuation=punctuation):
                old, new = '「A' + punctuation + 'B」', '「C' + punctuation + 'D」'
                found = engine.detect(old + 'じゃなく' + new + '。')
                self.assertEqual([(c.old, c.new) for c in found], [(old, new)])
                core = CompanionCore()
                core.handle(old + 'じゃなく' + new + '。', correction_key='name')
                self.assertEqual(core.state.snapshot()['name']['value'], new)
                core.replay()
                self.assertEqual(core.state.snapshot()['name']['value'], new)

    def test_thousands_separator_is_not_a_clause_separator(self):
        engine = CorrectionEngine()
        for text, old, new in (('1,000じゃなく2,000。', '1,000', '2,000'),
                               ('1,200,000じゃなく2,300,000。', '1,200,000', '2,300,000')):
            with self.subTest(text=text):
                correction = engine.detect(text)
                self.assertEqual(len(correction), 1)
                self.assertEqual((correction[0].old, correction[0].new), (old, new))
                core = CompanionCore()
                core.handle(text, correction_key='price')
                self.assertEqual(core.state.snapshot()['price']['value'], new)
                core.replay()
                self.assertEqual(core.state.snapshot()['price']['value'], new)

    def test_ascii_and_fullwidth_separators_keep_candidates_distinct(self):
        engine = CorrectionEngine()
        for separator in ('!', '！', ',', '、'):
            with self.subTest(separator=separator):
                found = engine.detect('赤じゃなく青' + separator + '緑じゃなく黄色。')
                self.assertEqual([x.new for x in found], ['青', '黄色'])
                core = CompanionCore()
                core.handle('青じゃなく緑', correction_key='color')
                core.handle('赤じゃなく青' + separator + '緑じゃなく黄色。', correction_key='color')
                self.assertEqual(core.state.snapshot()['color']['value'], '緑')
                core.replay()
                self.assertEqual(core.state.snapshot()['color']['value'], '緑')

    def test_overlong_replacement_is_not_silently_truncated(self):
        engine = CorrectionEngine()
        self.assertEqual(engine.detect('古い説明じゃなくて' + 'あ' * 60)[0].new, 'あ' * 60)
        self.assertEqual(engine.detect('古い説明じゃなくて' + 'あ' * 61), [])
        self.assertEqual(engine.detect('違う、' + 'あ' * 80)[0].new, 'あ' * 80)
        self.assertEqual(engine.detect('違う、' + 'あ' * 81), [])
        self.assertEqual(engine.detect('あ' * 41 + 'じゃなくて青'), [])
        self.assertEqual(engine.detect('赤じゃなくて青。古い説明じゃなくて' + 'あ' * 61), [])

    def test_unresolved_replacement_is_not_a_candidate(self):
        for text in ("違う、そこじゃない", "ちがう、そこではないです", "違う、それじゃないよ", "違う、そうじゃない", "違う、そこじゃないと思う", "違う、そこ", "違う、わからない", "君じゃなくてそれ"):
            with self.subTest(text=text):
                self.assertEqual(CorrectionEngine().detect(text), [])

    def test_incomplete_or_descriptive_input_is_not_a_candidate(self):
        for text in ("違う色の時計が好き", "君じゃなくて", "君ではなくて", "君じゃなく", "君ではなく", "君じゃなくて   ", "違う、君じゃなくて", "違う", "違う、", "違う2026"):
            with self.subTest(text=text):
                self.assertEqual(CorrectionEngine().detect(text), [])

    def test_concrete_replacement_and_negative_definition_still_work(self):
        for text, expected in (
            ("君じゃなくてルクルア", "ルクルア"),
            ("自然にっていうのは違和感がないという意味", "違和感がない"),
            ("違う、2026", "2026"),
            ("ちがう, 2026", "2026"),
            ("違う 2026", "2026"),
            ("違う、ルクルア", "ルクルア"),
            ("違う、君じゃなくてルクルア", "ルクルア"),
        ):
            with self.subTest(text=text):
                found = CorrectionEngine().detect(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].new, expected)

    def test_multiple_candidates_are_preserved_in_text_order(self):
        found = CorrectionEngine().detect("違う、2026。君じゃなくてルクルア")
        self.assertEqual([c.new for c in found], ["2026", "ルクルア"])


class CoreCorrectionAdmissionTests(unittest.TestCase):
    def test_reported_or_uncertain_correction_preserves_confirmed_memory(self):
        core = CompanionCore()
        core.handle('青じゃなくて緑', correction_key='favorite_color')
        before = core.state.snapshot()['favorite_color']
        previous = [(m.text, m.status) for m in core.memory.items if m.source == SourceType.USER_CORRECTION]
        for text in ('赤じゃなく青かもしれません。', '赤じゃなく青だと思います。',
                     '赤じゃなく青かもしれませんよ。', '赤じゃなく青だと思いますね。',
                     '赤じゃなく「青」と友達が言った。', '「赤じゃなく青」と言ったのは友達だ。'):
            core.handle(text, correction_key='favorite_color')
            self.assertEqual(core.state.snapshot()['favorite_color'], before)
            self.assertEqual([(m.text, m.status) for m in core.memory.items if m.source == SourceType.USER_CORRECTION], previous)
        core.replay()
        self.assertEqual(core.state.snapshot()['favorite_color'], before)
        self.assertEqual([(m.text, m.status) for m in core.memory.items if m.source == SourceType.USER_CORRECTION], previous)

    def test_negated_definition_does_not_replace_state_or_memory_on_replay(self):
        core = CompanionCore()
        core.handle('ルクルアっていうのは祭りって意味', correction_key='term.meaning')
        before = core.state.snapshot()['term.meaning']
        before_corrections = [m.text for m in core.memory.items if m.source == SourceType.USER_CORRECTION]
        text = 'ルクルアっていうのは大会って意味ではない'
        core.handle(text, correction_key='term.meaning')
        self.assertEqual(core.state.snapshot()['term.meaning'], before)
        self.assertEqual([m.text for m in core.memory.items if m.source == SourceType.USER_CORRECTION], before_corrections)
        self.assertTrue(any(e.kind == 'user_input' and e.payload['text'] == text for e in core.events.events))
        core.replay()
        self.assertEqual(core.state.snapshot()['term.meaning'], before)

    def test_overlong_negative_correction_is_not_promoted_even_after_replay(self):
        core = CompanionCore()
        text = '古い説明じゃなくて' + '背景' * 29 + '大会に参加するわけではない'
        core.handle(text, correction_key='meeting.detail')
        self.assertNotIn('meeting.detail', core.state.active)
        self.assertFalse(any(e.kind == 'correction' for e in core.events.events))
        self.assertTrue(any(e.kind == 'user_input' and e.payload['text'] == text for e in core.events.events))
        core.replay()
        self.assertNotIn('meeting.detail', core.state.active)
    def test_vague_correction_with_target_preserves_fact_history_and_events(self):
        core = CompanionCore()
        core.handle("君じゃなくてルクルア", correction_key="name")
        before = core.state.snapshot()["name"]
        blocked = set(core.state.blocked["name"])
        corrections = sum(e.kind == "correction" for e in core.events.events)
        for text in ("違う、そこじゃない", "ちがう、それではないです", "君じゃなくて", "違う色の時計が好き"):
            with self.subTest(text=text):
                context = core.handle(text, correction_key="name")
                self.assertEqual(core.state.snapshot()["name"], before)
                self.assertEqual(context["state"]["name"], "ルクルア")
                self.assertEqual(len(core.state.history["name"]), 1)
                self.assertEqual(core.state.blocked["name"], blocked)
                self.assertEqual(sum(e.kind == "correction" for e in core.events.events), corrections)
        committed_memory = [x.text for x in core.memory.items if x.source == SourceType.USER_CORRECTION]
        self.assertEqual(committed_memory, ["name = ルクルア"])
        # Raw user utterances remain ordinary memories/events, not verified facts.
        self.assertTrue(any(e.kind == "user_input" and e.payload["text"] == "違う、そこじゃない" for e in core.events.events))
        core.replay()
        self.assertEqual(core.state.active["name"].value, "ルクルア")

    def test_vague_correction_cannot_create_a_new_fact(self):
        for key in (None, "name"):
            with self.subTest(key=key):
                core = CompanionCore()
                core.handle("違う、そこじゃない", correction_key=key)
                self.assertNotIn("name", core.state.active)
                self.assertFalse(any(e.kind == "correction" for e in core.events.events))
                self.assertFalse(any(x.source == SourceType.USER_CORRECTION for x in core.memory.items))

    def test_concrete_correction_with_target_still_commits(self):
        core = CompanionCore()
        core.state.propose("year", "2023", SourceType.USER_STATEMENT)
        core.handle("違う、2026", correction_key="year")
        self.assertEqual(core.state.active["year"].value, "2026")
        self.assertIn("2023", core.state.blocked["year"])
        self.assertEqual(core.state.history["year"][0].status.value, "invalidated")

    def test_concrete_correction_without_target_remains_a_proposal(self):
        core = CompanionCore()
        core.handle("違う、2026")
        self.assertFalse(any(e.kind == "correction" for e in core.events.events))
        self.assertTrue(any(t["stage"] == "correction_proposal" for t in core.trace))

    def test_multiple_candidates_do_not_choose_first_for_one_key(self):
        core = CompanionCore()
        core.handle("君じゃなくてルクルア", correction_key="name")
        before = core.state.snapshot()["name"]
        core.handle("君じゃなくて別名。2023じゃなくて2026", correction_key="name")
        self.assertEqual(core.state.snapshot()["name"], before)
        self.assertEqual(sum(e.kind == "correction" for e in core.events.events), 1)
        proposal = next(t for t in reversed(core.trace) if t["stage"] == "correction_proposal")
        self.assertEqual(proposal["reason"], "multiple_candidates")


if __name__ == "__main__":
    unittest.main()
