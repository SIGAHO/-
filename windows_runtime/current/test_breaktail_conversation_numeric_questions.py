"""Regression: questions and guesses must not overwrite confirmed amounts."""
import unittest

from breaktail_conversation_state import update_session


class NumericConfirmationTests(unittest.TestCase):
    def test_budget_question_preserves_previous_value(self):
        state = {}
        update_session(state, "予算は6000円", "t1")
        update_session(state, "予算は5000円だったっけ？", "t2")
        facts = state["conversation"]["facts"]
        self.assertEqual(facts["budget"]["value"], 6000)
        self.assertEqual(facts["budget"]["turn"], "t1")
        self.assertEqual(state["conversation"]["last_changes"], [])

    def test_direct_correction_updates_budget(self):
        state = {}
        update_session(state, "予算は6000円", "t1")
        update_session(state, "予算は5000円に変更", "t2")
        self.assertEqual(state["conversation"]["facts"]["budget"]["value"], 5000)

    def test_lunch_confirmation_does_not_replace_amount(self):
        state = {}
        update_session(state, "昼食が一人1200円", "t1")
        update_session(state, "昼食が一人1500円だよね？", "t2")
        self.assertEqual(state["conversation"]["facts"]["lunch_each"]["value"], 1200)

    def test_conditional_cost_keeps_existing_calculation_path(self):
        state = {}
        update_session(state, "予算は6000円", "t1")
        update_session(state, "昼食が一人1200円なら残りは？", "t2")
        self.assertEqual(state["conversation"]["facts"]["lunch_each"]["value"], 1200)

    def test_question_does_not_create_new_amount_or_people(self):
        state = {}
        update_session(state, "予算は二人で5000円だったっけ？", "t1")
        self.assertNotIn("budget", state["conversation"]["facts"])
        self.assertNotIn("people", state["conversation"]["facts"])


if __name__ == "__main__":
    unittest.main()
