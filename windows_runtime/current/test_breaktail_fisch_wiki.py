import unittest
from unittest.mock import patch

from breaktail_fisch_wiki import lookup, select_fisch_term


class WikiTests(unittest.TestCase):
    def test_only_short_game_terms_can_be_looked_up(self):
        ocr = {"lines": [
            {"text": "player@example.com", "score": 0.99},
            {"text": "My private chat", "score": 0.99},
            {"text": "Fish Radar", "score": 0.94}]}
        self.assertEqual(select_fisch_term(ocr), "Fish Radar")
        self.assertEqual(select_fisch_term({"lines": [{"text": "Secret Rod", "score": 0.4}]}), "")

    def test_wiki_response_requires_matching_heading_and_source(self):
        class Response:
            status = 200
            url = "https://fisch.wiki/wiki/fish-radar/"
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, count):
                return b"<h1>Fish Radar</h1><p>Fish Radar shows fish in nearby areas and can be toggled.</p>"
        with patch("breaktail_fisch_wiki.request.urlopen", return_value=Response()):
            result = lookup("Fish Radar")
        self.assertEqual(result["title"], "Fish Radar")
        self.assertEqual(result["url"], Response.url)
        self.assertIn("nearby areas", result["excerpt"])


if __name__ == "__main__":
    unittest.main()

