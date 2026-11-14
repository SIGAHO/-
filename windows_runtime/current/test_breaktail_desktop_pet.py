"""No desktop or model is needed for the companion's small pure-function checks."""
import json
import unittest
from unittest.mock import patch

from breaktail_desktop_pet import (KeyboardActivity, classify_key, clean_comment, ease, hop_arc,
                                   screen_hint, vision_comment, window_category)


class DesktopPetTests(unittest.TestCase):
    def test_window_reaction_does_not_repeat_private_title(self):
        title = "private-document-name — Visual Studio Code"
        category = window_category(title)
        self.assertEqual(category, "作業画面")
        self.assertNotIn("private-document-name", category)

    def test_model_comment_drops_thinking_and_extra_lines(self):
        self.assertEqual(clean_comment("<think>hidden</think> 画面が明るいね。\n秘密"), "画面が明るいね。")
        self.assertNotIn("person@example.com", clean_comment("person@example.com が見えるね。"))

    def test_hop_has_rest_and_landing_with_a_visible_arc(self):
        self.assertEqual(hop_arc(0), 0)
        self.assertEqual(hop_arc(1), 0)
        self.assertGreater(hop_arc(0.5), 30)
        self.assertEqual(ease(0), 0)
        self.assertEqual(ease(1), 1)
        self.assertAlmostEqual(ease(0.5), 0.5)

    def test_ui_shape_and_key_categories_do_not_require_text(self):
        self.assertEqual(screen_hint("作業画面", {"available": True,
                         "types": {"EditControl": 1}, "focused_type": "EditControl"}),
                         "入力している画面みたい。")
        self.assertEqual(classify_key(ord("S"), True), "save")
        self.assertEqual(classify_key(ord("F"), True), "search")
        self.assertEqual(classify_key(0x25, False), "navigate")
        self.assertEqual(classify_key(ord("A"), False), "type")

    def test_keyboard_keeps_only_categories_and_short_window(self):
        activity = KeyboardActivity()
        pressed = {ord("A")}
        activity.poll(10.0, lambda key: 0x8000 if key in pressed else 0)
        self.assertEqual(activity.summary(), {"type": 1})
        activity.poll(10.1, lambda key: 0x8000 if key in pressed else 0)
        self.assertEqual(activity.summary(), {"type": 1})
        pressed = {0x11, ord("S")}
        activity.poll(10.2, lambda key: 0x8000 if key in pressed else 0)
        self.assertEqual(activity.summary(), {"type": 1, "save": 1})
        self.assertNotIn("A", str(activity.events))
        activity.poll(23.0, lambda key: 0)
        self.assertEqual(activity.summary(), {})

    def test_vision_call_stays_on_local_ollama_and_uses_small_model(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"message":{"content":"Looks calm."}}'

        with patch("breaktail_desktop_pet.request.urlopen", return_value=Response()) as call:
            answer = vision_comment(b"test-jpeg")
        self.assertEqual(answer, "Looks calm.")
        sent = call.call_args.args[0]
        self.assertEqual(sent.full_url, "http://127.0.0.1:11434/api/chat")
        body = json.loads(sent.data)
        self.assertEqual(body["model"], "qwen3.5:4b")
        self.assertEqual(body["messages"][0]["images"], ["dGVzdC1qcGVn"])
        self.assertFalse(body["stream"])


if __name__ == "__main__":
    unittest.main()

