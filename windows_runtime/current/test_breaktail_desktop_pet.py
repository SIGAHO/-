"""No desktop or model is needed for the companion's small pure-function checks."""
import json
import unittest
from unittest.mock import patch

from breaktail_desktop_pet import clean_comment, vision_comment, window_category


class DesktopPetTests(unittest.TestCase):
    def test_window_reaction_does_not_repeat_private_title(self):
        title = "private-document-name — Visual Studio Code"
        category = window_category(title)
        self.assertEqual(category, "作業画面")
        self.assertNotIn("private-document-name", category)

    def test_model_comment_drops_thinking_and_extra_lines(self):
        self.assertEqual(clean_comment("<think>hidden</think> 画面が明るいね。\n秘密"), "画面が明るいね。")
        self.assertNotIn("person@example.com", clean_comment("person@example.com が見えるね。"))

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

