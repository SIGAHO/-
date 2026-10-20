"""Topic identity, active focus, and accumulated strength are distinct."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore
from companion_core.topic import TopicTracker


class TopicBehaviorTests(unittest.TestCase):
    def test_current_switches_immediately_even_when_old_topic_ranks_first(self):
        tracker = TopicTracker()
        cnc = tracker.update("CNC基板")
        for _ in range(5):
            tracker.update("CNC基板")
        clock = tracker.update("時計")
        self.assertIs(tracker.current(), clock)
        self.assertIs(tracker.ranked()[0], cnc)
        self.assertIs(tracker.update("CNC基板"), cnc)
        self.assertIs(tracker.current(), cnc)
        self.assertEqual(len(tracker.topics), 2)

    def test_paraphrase_keeps_original_identity(self):
        tracker = TopicTracker()
        first = tracker.update("CNCで基板を削る")
        self.assertIs(tracker.update("プリント配線板を切削加工する"), first)
        self.assertEqual(len(tracker.topics), 1)

    def test_additional_board_aliases_and_verb_forms_share_identity(self):
        tracker = TopicTracker()
        first = tracker.update("PCBを製作する")
        for text in ("プリント基板の加工について知りたい", "基板を作りたい", "プリント配線板を調べる"):
            with self.subTest(text=text):
                self.assertIs(tracker.update(text), first)
        self.assertEqual(len(tracker.topics), 1)

    def test_shared_actions_do_not_merge_known_different_subjects(self):
        tracker = TopicTracker()
        topics = [tracker.update(text) for text in ("時計を作る", "寿司を作る", "基板を作る")]
        self.assertEqual(len(tracker.topics), 3)
        self.assertEqual(len({id(t) for t in topics}), 3)
        self.assertIs(tracker.update("すしを製作する"), topics[1])

    def test_shared_actions_do_not_merge_unknown_different_subjects(self):
        tracker = TopicTracker()
        chair = tracker.update("椅子を作る")
        desk = tracker.update("机を作る")
        self.assertIsNot(chair, desk)
        self.assertEqual(len(tracker.topics), 2)
        self.assertIs(tracker.update("椅子を製作する"), chair)

    def test_shared_tool_does_not_override_different_known_objects(self):
        tracker = TopicTracker()
        board = tracker.update("CNCで基板を作る")
        clock = tracker.update("CNCで時計を作る")
        self.assertIsNot(board, clock)
        self.assertEqual(len(tracker.topics), 2)

    def test_comparison_does_not_contaminate_single_subject_topics(self):
        tracker = TopicTracker()
        board = tracker.update("基板を作る")
        clock = tracker.update("時計を作る")
        comparison = tracker.update("基板と時計の比較")
        self.assertIsNot(comparison, board)
        self.assertIsNot(comparison, clock)
        self.assertIs(tracker.update("時計を調べる"), clock)
        self.assertIs(tracker.update("プリント配線板を調べる"), board)
        self.assertEqual(len(tracker.topics), 3)

    def test_generic_action_alone_keeps_current_without_adding_strength(self):
        tracker = TopicTracker()
        self.assertIsNone(tracker.update("作る"))
        topic = tracker.update("時計")
        score = topic.score
        for text in ("作る", "仕組みについて調べる", "   ", "！！！"):
            with self.subTest(text=text):
                self.assertIs(tracker.update(text), topic)
                self.assertIs(tracker.current(), topic)
                self.assertEqual(topic.score, score)
        self.assertEqual(len(tracker.topics), 1)

    def test_configured_noun_aliases_work_outside_default_domains(self):
        tracker = TopicTracker(aliases={"電池": ("バッテリー", "battery")})
        first = tracker.update("電池を作る")
        self.assertIs(tracker.update("batteryを製作する"), first)
        self.assertIs(tracker.update("バッテリーを調べる"), first)

    def test_single_character_and_case_normalization_are_preserved(self):
        tracker = TopicTracker()
        cat = tracker.update("猫")
        self.assertIs(tracker.update("猫"), cat)
        board = tracker.update("CNC PCB")
        self.assertIs(tracker.update("cnc pcb"), board)

    def test_ascii_alias_does_not_match_inside_another_identifier(self):
        tracker = TopicTracker()
        board = tracker.update("PCB")
        identifier = tracker.update("pcbackup")
        self.assertIsNot(identifier, board)


class CoreTopicTests(unittest.TestCase):
    def test_context_and_replay_preserve_switch_return_and_paraphrase(self):
        core = CompanionCore()
        for _ in range(4):
            core.handle("CNCで基板を削る")
        context = core.handle("時計を作る")
        self.assertEqual(context["topic"]["label"], "時計を作る")
        self.assertEqual(core.topic.current().label, "時計を作る")
        context = core.handle("プリント配線板を切削加工する")
        self.assertEqual(context["topic"]["label"], "CNCで基板を削る")
        before = [(t.label, t.score, set(t.signature)) for t in core.topic.topics]
        core.replay()
        self.assertEqual(core.topic.current().label, "CNCで基板を削る")
        self.assertEqual([(t.label, t.score, set(t.signature)) for t in core.topic.topics], before)


if __name__ == "__main__":
    unittest.main()
