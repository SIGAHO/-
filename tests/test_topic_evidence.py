"""Structural/metamorphic fixtures, not corpus labels or training examples."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore
from companion_core.topic import TopicTracker


class EvidencePolicyTests(unittest.TestCase):
    def tracker(self):
        return TopicTracker(policy="evidence", use_default_aliases=False)

    def test_elliptical_responses_and_attribute_questions_keep_focus(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        for text in ("ありがとうございます", "そうですか", "それはどうですか", "vupの値は何ですか", "123です"):
            with self.subTest(text=text):
                self.assertIs(tracker.update(text), first)
        self.assertEqual(len(tracker.topics), 1)

    def test_unknown_object_replacement_switches_without_domain_aliases(self):
        for a, b in (("qax", "zup"), ("nuv", "wex"), ("kiv", "pof")):
            with self.subTest(a=a, b=b):
                tracker = self.tracker()
                first = tracker.update(f"{a}を作る")
                second = tracker.update(f"{b}を作る")
                self.assertIsNot(first, second)
                self.assertIs(tracker.update(f"{a}を作る"), first)

    def test_low_overlap_requires_two_independently_supported_turns(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        self.assertIs(tracker.update("zupの設計を進めています"), first)
        self.assertEqual(tracker.last_decision, "pending")
        second = tracker.update("zupの寸法を見直しています")
        self.assertIsNot(second, first)
        self.assertEqual(len(tracker.topics), 2)
        self.assertIs(tracker.current(), second)

    def test_pending_vocabulary_does_not_pollute_current_anchor(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        before = set(first.signature)
        tracker.update("zupの設計を進めています")
        self.assertEqual(first.signature, before)
        self.assertEqual(len(tracker.topics), 1)

    def test_matching_current_clears_stale_pending_candidate(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        tracker.update("zupの設計を進めています")
        tracker.update("qaxを作る")
        self.assertIs(tracker.update("zupの寸法を見直しています"), first)
        self.assertEqual(tracker.last_decision, "pending")

    def test_title_switch_and_return_do_not_require_confirmation(self):
        tracker = self.tracker()
        first = tracker.update("qax")
        second = tracker.update("zup")
        self.assertIsNot(first, second)
        self.assertIs(tracker.update("qax"), first)

    def test_fresh_case_marked_object_can_introduce_a_different_request(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        second = tracker.update("zupを調べてください")
        self.assertIsNot(first, second)
        third = tracker.update("nuvを確認してもらえますか")
        self.assertIsNot(second, third)

    def test_pronominal_object_question_still_stays_with_current(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        self.assertIs(tracker.update("それを確認してもらえますか"), first)

    def test_independent_subject_or_topic_can_introduce_new_focus(self):
        for text in ("zupは使えますか", "zupが必要です", "zupを調べます"):
            with self.subTest(text=text):
                tracker = self.tracker()
                first = tracker.update("qaxを作る")
                self.assertIsNot(tracker.update(text), first)

    def test_many_unrelated_questions_do_not_create_unbounded_topics(self):
        tracker = self.tracker()
        first = tracker.update("qaxを作る")
        for i in range(40):
            self.assertIs(tracker.update(f"field{i}の値は何ですか"), first)
        self.assertEqual(len(tracker.topics), 1)

    def test_replay_restores_pending_confirmation_behavior(self):
        core = CompanionCore()
        core.handle("qaxを作る")
        core.handle("zupの設計を進めています")
        pending = core.topic._pending
        core.replay()
        self.assertEqual(core.topic._pending, pending)
        core.handle("zupの寸法を見直しています")
        self.assertEqual(len(core.topic.topics), 2)
        self.assertEqual(core.topic.current().label, "zupの設計を進めています")


if __name__ == "__main__":
    unittest.main()
