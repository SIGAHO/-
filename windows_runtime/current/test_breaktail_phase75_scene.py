import json
import unittest
from test_model_isolation import ModelIsolatedCase
from unittest.mock import patch

import breaktail_v02 as tail
import breaktail_web as web


class ScenePersistenceTests(ModelIsolatedCase):
    def setUp(self):
        self.scene = {
            "name": "騎士ごっこ",
            "user_role": "騎士",
            "assistant_role": "相棒",
            "source": "騎士ごっこを始めよう",
        }

    def test_null_change_keeps_existing_scene(self):
        self.assertEqual(tail.apply_scene_change(self.scene, "剣を構える", None), self.scene)

    def test_invalid_candidate_does_not_silently_end_scene(self):
        invalid = {"action": "continue", "evidence": "別の発言"}
        self.assertEqual(tail.apply_scene_change(self.scene, "剣を構える", invalid), self.scene)

    def test_explicit_leave_ends_scene(self):
        change = {"action": "leave", "evidence": "ごっこは終わり"}
        self.assertIsNone(tail.apply_scene_change(self.scene, "ごっこは終わり", change))

    def test_extractor_null_keeps_scene(self):
        result = {
            "message": {"content": json.dumps({
                "subject_resolution": "unknown",
                "scene_change": None,
                "memory": None,
                "memory_evidence": None,
            }, ensure_ascii=False)},
            "done_reason": "stop",
        }
        with patch.object(tail, "call_ollama", return_value=result):
            memory, scene = tail.extract_interpretation("剣を構える", self.scene)
        self.assertIsNone(memory)
        self.assertEqual(scene, self.scene)

    def test_extractor_failure_keeps_scene(self):
        with patch.object(tail, "call_ollama", side_effect=RuntimeError("offline")):
            memory, scene = tail.extract_interpretation("剣を構える", self.scene)
        self.assertIsNone(memory)
        self.assertEqual(scene, self.scene)

    def test_cli_and_web_fallback_keep_same_scene(self):
        for prepare in (tail.prepare_turn, web.prepare_turn):
            with self.subTest(route=prepare.__module__), \
                 patch.object(tail, "extract_interpretation", side_effect=RuntimeError("offline")), \
                 patch.object(tail, "generate_reply", return_value=("剣を構えた。", True)) as generate:
                result = prepare([], "剣を構える", self.scene)
                self.assertEqual(result[:4], ("剣を構えた。", True, None, self.scene))
                self.assertIn("offline", result[4])
                self.assertEqual(generate.call_args.args[2], self.scene)


if __name__ == "__main__":
    unittest.main()
