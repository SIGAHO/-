"""Completion evidence must be positive and identify one pending task."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from companion_core import CompanionCore
from companion_core.open_loops import OpenLoopTracker


class OpenLoopBehaviorTests(unittest.TestCase):
    def test_qualified_or_other_person_completion_does_not_close_task(self):
        for text in ('レポートを提出したとは言ってない', 'レポートを提出したとは限らない',
                     'レポートを提出したかもしれない', '田中はレポートを提出した',
                     'レポートを提出したのは田中だ'):
            with self.subTest(text=text):
                tracker = OpenLoopTracker()
                tracker.observe('あとでレポートを提出する')
                tracker.observe(text)
                self.assertEqual(len(tracker.active()), 1)
        for text in ('レポートは提出した', 'レポートを提出したのは私だ', 'レポートを提出したのは昨日だ', 'レポートを提出したのは午後3時だ'):
            with self.subTest(text=text):
                tracker = OpenLoopTracker()
                tracker.observe('あとでレポートを提出する')
                tracker.observe(text)
                self.assertEqual(tracker.active(), [])

    def test_quoted_example_is_not_a_plan_but_quoted_plan_is(self):
        tracker = OpenLoopTracker()
        tracker.observe('「あとでレポートを提出する」という例文')
        self.assertEqual(tracker.active(), [])
        tracker.observe('「レポート提出」をあとでやる')
        self.assertEqual(len(tracker.active()), 1)

    def test_other_person_and_shared_verb_do_not_complete_user_task(self):
        for text in ('友達が書類を提出した', '書類を提出した', '友達が宿題を提出した', '田中が宿題を提出した'):
            with self.subTest(text=text):
                tracker = OpenLoopTracker()
                tracker.observe('あとで宿題を提出する')
                tracker.observe(text)
                self.assertEqual([x.text for x in tracker.active()], ['あとで宿題を提出する'])
        tracker = OpenLoopTracker()
        tracker.observe('あとで宿題を提出する')
        tracker.observe('宿題を提出した')
        self.assertEqual(tracker.active(), [])

    def test_bare_completion_closes_only_pending_task_without_deleting_it(self):
        for report in ("終わった", " 終わった！ ", "完了", "できた", "済んだ"):
            with self.subTest(report=report):
                tracker = OpenLoopTracker()
                tracker.observe("あとでやる")
                original = tracker.active()[0]
                tracker.observe(report)
                self.assertEqual(tracker.active(), [])
                self.assertIs(tracker.loops[0], original)
                self.assertTrue(original.done)

    def test_bare_completion_leaves_multiple_pending_tasks_ambiguous(self):
        tracker = OpenLoopTracker()
        tracker.observe("基板を実装する")
        tracker.observe("時計を調べる")
        before = list(tracker.active())
        tracker.observe("終わった")
        self.assertEqual(tracker.active(), before)

    def test_unfinished_reports_neither_close_nor_create_duplicate_tasks(self):
        for report in (
            "まだ終わってない", "基板の実装はまだ終わっていない",
            "基板の実装はまだ終わったわけじゃない", "基板の実装は終わったわけではない",
            "基板の実装は完了していない", "基板の実装は完了していません",
            "基板の実装はできてない", "基板の実装は済んでいない", "基板の実装は未完了",
        ):
            with self.subTest(report=report):
                tracker = OpenLoopTracker()
                tracker.observe("基板を実装する")
                before = list(tracker.active())
                tracker.observe(report)
                self.assertEqual(tracker.active(), before)
                self.assertEqual(len(tracker.loops), 1)
                self.assertFalse(before[0].done)

    def test_denied_plan_does_not_create_or_cancel_task(self):
        for report in ("やる予定がない", "基板を実装する予定がない", "基板を実装する予定はありません", "あとでやらない", "基板を確認しない"):
            with self.subTest(report=report):
                tracker = OpenLoopTracker()
                tracker.observe(report)
                self.assertEqual(tracker.loops, [])
                tracker.observe("時計を調べる")
                original = tracker.active()[0]
                tracker.observe(report)
                self.assertEqual(tracker.loops, [original])
                self.assertFalse(original.done)

    def test_obligation_is_not_mistaken_for_negative_plan(self):
        for text in ("あとでやらないと", "基板を確認しないと", "基板を実装しないと"):
            with self.subTest(text=text):
                tracker = OpenLoopTracker()
                tracker.observe(text)
                self.assertEqual([x.text for x in tracker.active()], [text])

    def test_named_completion_closes_matching_task_only(self):
        tracker = OpenLoopTracker()
        tracker.observe("基板を実装する")
        tracker.observe("時計を調べる")
        tracker.observe("時計を調べるのが終わった")
        self.assertEqual([x.text for x in tracker.active()], ["基板を実装する"])

    def test_equal_scoring_completion_does_not_choose_arbitrary_task(self):
        tracker = OpenLoopTracker()
        tracker.observe("基板を確認する")
        tracker.observe("時計を確認する")
        tracker.observe("確認する作業が完了")
        self.assertEqual(len(tracker.active()), 2)

    def test_question_or_conditional_is_not_completion_evidence(self):
        for report in ("終わった？", "基板の実装は終わった?", "基板の実装は完了ですか", "基板の実装が終わったら教えて"):
            with self.subTest(report=report):
                tracker = OpenLoopTracker()
                tracker.observe("基板を実装する")
                original = tracker.active()[0]
                tracker.observe(report)
                self.assertEqual(tracker.loops, [original])
                self.assertFalse(original.done)

    def test_duplicate_and_new_task_after_completion(self):
        tracker = OpenLoopTracker()
        tracker.observe("あとでやる")
        tracker.observe("あとでやる")
        self.assertEqual(len(tracker.loops), 1)
        tracker.observe("終わった")
        tracker.observe("あとでやる")
        self.assertEqual([x.done for x in tracker.loops], [True, False])


class CoreOpenLoopTests(unittest.TestCase):
    def test_uncertain_completion_remains_open_after_replay(self):
        core = CompanionCore()
        core.handle('あとでレポートを提出する')
        core.handle('レポートを提出したかもしれない')
        core.replay()
        self.assertEqual([x.text for x in core.open_loops.active()], ['あとでレポートを提出する'])

    def test_other_person_completion_remains_open_after_replay(self):
        core = CompanionCore()
        core.handle('あとで宿題を提出する')
        core.handle('友達が書類を提出した')
        self.assertEqual([x.text for x in core.open_loops.active()], ['あとで宿題を提出する'])
        core.replay()
        self.assertEqual([x.text for x in core.open_loops.active()], ['あとで宿題を提出する'])

    def test_context_and_replay_keep_completion(self):
        core = CompanionCore()
        self.assertEqual(core.handle("あとでやる")["open_loops"], ["あとでやる"])
        self.assertEqual(core.handle("終わった")["open_loops"], [])
        core.replay()
        self.assertEqual(core.open_loops.active(), [])
        self.assertEqual(len(core.open_loops.loops), 1)
        self.assertTrue(core.open_loops.loops[0].done)

    def test_context_and_replay_preserve_unfinished_task_and_ignore_denied_plan(self):
        core = CompanionCore()
        core.handle("基板を実装する")
        self.assertEqual(core.handle("基板の実装はまだ終わったわけじゃない")["open_loops"], ["基板を実装する"])
        self.assertEqual(core.handle("時計を調べる予定がない")["open_loops"], ["基板を実装する"])
        core.replay()
        self.assertEqual([x.text for x in core.open_loops.active()], ["基板を実装する"])
        self.assertEqual(len(core.open_loops.loops), 1)


if __name__ == "__main__":
    unittest.main()
