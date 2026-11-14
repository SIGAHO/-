from types import SimpleNamespace
import unittest

from breaktail_ocr_probe import parse_result, safe_text


class OcrProbeTests(unittest.TestCase):
    def test_redacts_contact_details_and_secret_fields(self):
        self.assertEqual(safe_text("password: hunter2"), "")
        self.assertNotIn("person@example.com", safe_text("person@example.com"))
        self.assertNotIn("123456789", safe_text("番号 123456789"))

    def test_keeps_high_confidence_text_with_position(self):
        result = SimpleNamespace(boxes=[[[20, 10], [120, 10], [120, 50], [20, 50]],
                                        [[160, 10], [190, 10], [190, 30], [160, 30]]],
                                 txts=["設定を保存", "読めない"], scores=[0.99, 0.31])
        parsed = parse_result(result, 300, 100, 1.2)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["lines"][0]["text"], "設定を保存")
        self.assertEqual(parsed["lines"][0]["region"], "left")
        self.assertEqual(parsed["lines"][0]["box"], [67, 100, 400, 500])


if __name__ == "__main__":
    unittest.main()

