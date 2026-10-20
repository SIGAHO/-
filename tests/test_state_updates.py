"""State updates must be idempotent without losing authority or provenance."""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore, SourceType
from companion_core.correction import CorrectionEngine
from companion_core.models import Scope, Status
from companion_core.memory import MemoryEngine
from companion_core.state import StateEngine


class StateUpdateTests(unittest.TestCase):
    def test_same_assertion_is_noop_including_identity_and_timestamps(self):
        state = StateEngine()
        state.propose("name", "ルクルア", SourceType.USER_STATEMENT)
        original = state.active["name"]
        before = state.snapshot()
        for _ in range(100):
            self.assertTrue(state.propose("name", "ルクルア", SourceType.USER_STATEMENT))
        self.assertIs(state.active["name"], original)
        self.assertEqual(state.snapshot(), before)
        self.assertEqual(state.history["name"], [original])

    def test_same_value_authority_upgrade_supersedes_with_provenance(self):
        state = StateEngine()
        state.propose("year", 2026, SourceType.VERIFIED_MEMORY)
        old = state.active["year"]
        self.assertTrue(state.propose("year", 2026, SourceType.USER_STATEMENT))
        new = state.active["year"]
        self.assertEqual(len(state.history["year"]), 2)
        self.assertEqual(old.status, Status.INVALIDATED)
        self.assertEqual(old.superseded_by, new.id)
        self.assertEqual(new.source, SourceType.USER_STATEMENT)
        self.assertFalse(state.propose("year", 2026, SourceType.VERIFIED_MEMORY))

    def test_same_value_scope_change_is_not_discarded(self):
        state = StateEngine()
        state.propose("name", "ルクルア", SourceType.USER_STATEMENT)
        old = state.active["name"]
        state.propose("name", "ルクルア", SourceType.USER_STATEMENT, Scope.LONG_TERM)
        self.assertEqual(state.active["name"].scope, Scope.LONG_TERM)
        self.assertEqual(old.status, Status.INVALIDATED)
        self.assertEqual(old.superseded_by, state.active["name"].id)
        self.assertEqual(len(state.history["name"]), 2)

    def test_same_value_does_not_bypass_source_gate(self):
        state = StateEngine()
        state.correct("year", 2026)
        before = state.snapshot()
        self.assertFalse(state.propose("year", 2026, SourceType.ASSISTANT_GENERATED))
        self.assertFalse(state.propose("year", 2026, SourceType.USER_STATEMENT))
        self.assertEqual(state.snapshot(), before)
        self.assertEqual(len(state.history["year"]), 1)

    def test_repeated_correction_is_noop_but_upgrade_to_correction_is_recorded(self):
        state = StateEngine()
        state.propose("year", "2026", SourceType.USER_STATEMENT)
        old = state.active["year"]
        first = state.correct("year", "2026")
        self.assertEqual(old.status, Status.INVALIDATED)
        self.assertEqual(old.superseded_by, first.id)
        self.assertIs(state.correct("year", "2026"), first)
        self.assertEqual(len(state.history["year"]), 2)

    def test_equal_python_values_with_different_types_are_not_deduplicated(self):
        state = StateEngine()
        state.propose("value", 1, SourceType.USER_STATEMENT)
        old = state.active["value"]
        state.propose("value", True, SourceType.USER_STATEMENT)
        self.assertIs(state.active["value"].value, True)
        self.assertEqual(old.status, Status.INVALIDATED)
        self.assertEqual(len(state.history["value"]), 2)


class UserYearStateTests(unittest.TestCase):
    def test_targeted_year_statement_corrects_old_value_and_replays(self):
        for key in ("year", "time.user_year"):
            with self.subTest(key=key):
                core = CompanionCore()
                core.handle("違う、2023", correction_key=key)
                old = core.state.active[key]
                context = core.handle("今年は2026", correction_key=key)
                self.assertEqual(context["state"][key], "2026")
                self.assertEqual(core.state.active[key].source, SourceType.USER_CORRECTION)
                self.assertEqual(old.status, Status.INVALIDATED)
                self.assertEqual(old.superseded_by, core.state.active[key].id)
                self.assertIn("2023", core.state.blocked[key])
                self.assertFalse(core.state.propose(key, "2023", SourceType.USER_STATEMENT))
                self.assertTrue(any(e.kind == "correction" and e.payload["new"] == "2026" for e in core.events.events))
                self.assertTrue(any(m.source == SourceType.USER_CORRECTION and m.text == f"{key} = 2026" for m in core.memory.items))
                core.replay()
                self.assertEqual(core.state.active[key].value, "2026")
                self.assertIn("2023", core.state.blocked[key])
                self.assertEqual([f.status for f in core.state.history[key]], [Status.INVALIDATED, Status.ACTIVE])

    def test_repeating_year_statement_does_not_duplicate_history_or_drop_events(self):
        core = CompanionCore()
        core.handle("今年は2026", correction_key="year")
        first = core.state.active["year"]
        core.handle("今年は2026", correction_key="year")
        self.assertIs(core.state.active["year"], first)
        self.assertEqual(len(core.state.history["year"]), 1)
        self.assertEqual(sum(e.kind == "user_input" for e in core.events.events), 2)
        core.replay()
        self.assertEqual(len(core.state.history["year"]), 1)
        self.assertEqual(core.state.active["year"].value, "2026")

    def test_plain_year_remains_outside_generic_correction_detector(self):
        self.assertEqual(CorrectionEngine().detect("今年は2026"), [])
        core = CompanionCore()
        core.handle("今年は2026")
        self.assertNotIn("year", core.state.active)
        self.assertNotIn("time.user_year", core.state.active)

    def test_only_complete_unambiguous_year_assertions_are_admitted(self):
        for text in ("今年は2026？", "今年は2026ではない", "今年は2026なら", "彼は『今年は2026』と言った", "今年は0000", "今年は20260", "今年は2026。違う、2027"):
            with self.subTest(text=text):
                core = CompanionCore()
                core.handle(text, correction_key="year")
                # The last example contains an explicit generic correction to
                # 2027; it must not be overwritten by a partial 2026 match.
                if "違う、2027" in text:
                    self.assertEqual(core.state.active["year"].value, "2027")
                else:
                    self.assertNotIn("year", core.state.active)

    def test_year_statement_does_not_write_unrelated_or_runtime_key(self):
        for key in ("name", "time.year"):
            with self.subTest(key=key):
                core = CompanionCore()
                core.handle("今年は2023", correction_key=key)
                self.assertNotIn("name", core.state.active)
                self.assertEqual(core.state.active["time.year"].source, SourceType.RUNTIME)
                self.assertFalse(any(e.kind == "correction" for e in core.events.events))

    def test_runtime_reobservations_do_not_duplicate_unchanged_facts(self):
        fixed = datetime(2026, 10, 21, 9, tzinfo=timezone(timedelta(hours=9)))
        with patch("companion_core.time_engine.TimeEngine.now", return_value=fixed):
            core = CompanionCore()
            core.handle("こんにちは")
            core.handle("続きやろう")
        self.assertEqual(core.state.active["time.year"].value, 2026)
        self.assertTrue(all(len(facts) == 1 for facts in core.state.history.values()))

    def test_changed_correction_value_is_not_an_approximate_memory_duplicate(self):
        memory = MemoryEngine()
        for text in ("time.user_year = 2023", "time.user_year = 2026", "time.user_year = 2026"):
            memory.add(text, SourceType.USER_CORRECTION)
        self.assertEqual([m.text for m in memory.items], ["time.user_year = 2023", "time.user_year = 2026"])
        self.assertEqual([m.mentions for m in memory.items], [1, 2])

    def test_correction_memory_preserves_source_against_statement_duplicates(self):
        for first, second in ((SourceType.USER_STATEMENT, SourceType.USER_CORRECTION), (SourceType.USER_CORRECTION, SourceType.USER_STATEMENT)):
            with self.subTest(first=first):
                memory = MemoryEngine()
                memory.add("year = 2026", first)
                memory.add("year = 2026", second)
                self.assertEqual([m.source for m in memory.items], [first, second])


if __name__ == "__main__":
    unittest.main()
