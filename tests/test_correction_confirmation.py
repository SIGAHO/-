"""Correction admission must preserve facts when no replacement is specified."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore, SourceType
from companion_core.correction import CorrectionEngine


class CorrectionConfirmationTests(unittest.TestCase):
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
