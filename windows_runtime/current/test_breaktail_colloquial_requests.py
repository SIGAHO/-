"""Regressions for ordinary Japanese requests without punctuation."""
import unittest
from breaktail_request_intent import explicit_request
from breaktail_reply_contract import build_contract, violations
from breaktail_working_state import new_working_state


class ColloquialRequestsTests(unittest.TestCase):
    def test_requests_not_mistaken_for_casual_sharing(self):
        cases = (
            "なんで動かないの",
            "これ直して",
            "これ調べてくれ",
            "原因を説明して",
            "何が問題なの",
            "これ比較して",
            "続けて",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(explicit_request(text))
                contract = build_contract(new_working_state(), text)
                self.assertTrue(contract["requested_response"])
                self.assertFalse(contract["concrete_sharing"])
                self.assertFalse(contract["no_advice"])
                self.assertIn("acknowledgement_instead_of_requested_response",
                              violations("了解。", contract))

    def test_real_sharing_and_quoted_command_not_requests(self):
        cases = (
            "買ったばかりの手袋を片方なくした。",
            "昨日壊れた時計を直してくれた。",
            "友達が『直して』と言った。",
            "「調べて」って言われた。",
            "昨日はなんでだろうと思った。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(explicit_request(text))

    def test_persistent_no_advice_is_not_erased_by_simple_story(self):
        state = new_working_state()
        state["conversation"]["preferences"]["no_advice"] = True
        self.assertTrue(build_contract(state,"朝に時計を落とした。")["no_advice"])
        # A requested technical answer must still be considered a response.
        contract = build_contract(state, "これ直して")
        self.assertTrue(contract["requested_response"])
        self.assertFalse(contract["no_advice"])
        self.assertTrue(build_contract(state, "昨日は時計を直してもらった。")["no_advice"])


if __name__ == "__main__":
    unittest.main()
