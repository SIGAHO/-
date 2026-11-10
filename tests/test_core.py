import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from companion_core import CompanionCore, SourceType
from companion_core.state import StateEngine
from companion_core.models import Scope
from companion_core.correction import CorrectionEngine
from companion_core.memory import MemoryEngine


class StateTests(unittest.TestCase):
    def test_ai_cannot_write_state(self):
        s = StateEngine()
        self.assertFalse(s.propose("year", 2023, SourceType.ASSISTANT_GENERATED))
        self.assertNotIn("year", s.active)

    def test_user_correction_hard_wins(self):
        s = StateEngine()
        s.propose("year", 2023, SourceType.USER_STATEMENT)
        s.correct("year", 2026, 2023)
        self.assertEqual(s.active["year"].value, 2026)
        self.assertIn("2023", s.blocked["year"])
        self.assertFalse(s.propose("year", 2023, SourceType.USER_STATEMENT))

    def test_runtime_beats_normal_statement(self):
        s = StateEngine()
        s.propose("clock.hour", 16, SourceType.RUNTIME, Scope.TURN)
        self.assertFalse(s.propose("clock.hour", 9, SourceType.USER_STATEMENT))
        self.assertEqual(s.active["clock.hour"].value, 16)


class CorrectionTests(unittest.TestCase):
    def test_a_not_b(self):
        c = CorrectionEngine().detect("君じゃなくてルクルア")
        self.assertTrue(c)
        self.assertEqual(c[0].old, "君")
        self.assertEqual(c[0].new, "ルクルア")

    def test_meaning_pattern(self):
        c = CorrectionEngine().detect("自然にっていうのは違和感がないという意味")
        self.assertTrue(c)
        self.assertIn("違和感", c[0].new)


class MemoryTests(unittest.TestCase):
    def test_ai_cannot_enter_memory(self):
        m = MemoryEngine()
        self.assertFalse(m.add("AI guessed fact", SourceType.ASSISTANT_GENERATED))
        self.assertEqual(m.items, [])

    def test_unrelated_recent_memory_is_not_recalled(self):
        m = MemoryEngine()
        m.add("今日はカレーを食べた", SourceType.USER_STATEMENT, 0.8)
        self.assertEqual(m.retrieve("時計の脱進機"), [])

    def test_retrieval_prefers_related(self):
        m = MemoryEngine()
        m.add("CNCで基板を削る", SourceType.USER_STATEMENT, 0.6)
        m.add("時計の脱進機を作る", SourceType.USER_STATEMENT, 0.6)
        got = m.retrieve("CNC基板")
        self.assertTrue(got)
        self.assertIn("CNC", got[0].text)


class CoreTests(unittest.TestCase):
    def test_correction_without_target_is_not_committed(self):
        c = CompanionCore()
        c.handle("君じゃなくてルクルア")
        self.assertFalse(any(v["value"] == "ルクルア" for v in c.state.snapshot().values()))

    def test_correction_with_target_is_committed(self):
        c = CompanionCore()
        c.handle("2023", correction_key=None)
        c.handle("違う、2026", correction_key="time.user_year")
        self.assertEqual(c.state.active["time.user_year"].value, "2026")

    def test_assistant_output_never_changes_state(self):
        c = CompanionCore()
        before = c.state.snapshot().copy()
        c.record_assistant_output("今年は2023です")
        self.assertEqual(before, c.state.snapshot())

    def test_context_contains_model_less_parts(self):
        c = CompanionCore()
        ctx = c.handle("あとでメモリの式を作る")
        self.assertIn("runtime", ctx)
        self.assertIn("topic", ctx)
        self.assertIn("open_loops", ctx)
        self.assertIn("memory", ctx)
        self.assertIn("emotion", ctx)
        self.assertTrue(ctx["open_loops"])


    def test_event_log_restores_memories_and_corrections_on_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.jsonl"
            first = CompanionCore(event_path=path)
            first.handle("時計の脱進機を作る")
            first.handle("違う、2026", correction_key="time.user_year")
            first.record_assistant_output("AIが勝手に作った発言")
            second = CompanionCore(event_path=path)
            self.assertEqual(second.state.active["time.user_year"].value, "2026")
            self.assertIn("時計の脱進機を作る", [m.text for m in second.memory.items])
            self.assertIn("time.user_year = 2026", [m.text for m in second.memory.items])
            self.assertNotIn("AIが勝手に作った発言", [m.text for m in second.memory.items])
            self.assertEqual(second.diagnostics()["event_count"], 4)
            second.replay()
            self.assertEqual(second.state.active["time.user_year"].value, "2026")

    def test_current_utterance_is_not_retrieved_as_old_memory(self):
        c = CompanionCore()
        first = c.handle("新しい独自の識別番号XYZ777")
        self.assertNotIn("新しい独自の識別番号XYZ777", first["memory"])
        second = c.handle("新しい独自の識別番号XYZ777")
        self.assertIn("新しい独自の識別番号XYZ777", second["memory"])



if __name__ == "__main__":
    unittest.main()
