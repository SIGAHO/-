import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import breaktail_memory_manager as manager
import breaktail_v02 as tail


def profile_items():
    return [
        {"number": number, "label": f"項目{number}", "value": f"値{number}"}
        for number in range(1, 21)
    ]


class MemoryProfileTeachTests(unittest.TestCase):
    def test_forget_removes_memory_from_store_and_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "memory.jsonl"
            rows = [
                {"id": 1, "content": "星空観察が好き"},
                {"id": 2, "content": "紅茶が好き"},
            ]
            store.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            with patch.object(tail, "MEMORY_FILE", store):
                self.assertTrue(tail.retrieve_memory_candidates("星空観察"))
                backup = tail.forget_memory(1)
                self.assertEqual(tail.retrieve_memory_candidates("星空観察"), [])
                remaining = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(backup.exists())
            self.assertEqual([row["id"] for row in remaining], [2])

    def test_verified_profile_round_trip_and_corrupt_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "profile.json"
            saved = manager.save_verified_profile(profile_items(), path)
            self.assertEqual(manager.load_profile(path), saved)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(manager.ProfileStoreError):
                manager.load_profile(path)

            with patch.object(tail, "load_profile", side_effect=manager.ProfileStoreError("broken")), \
                 patch.object(tail, "MEMORY_FILE", Path(temp_dir) / "missing-memory.jsonl"):
                messages = tail.build_reply_messages([], "こんにちは", None)
            self.assertNotIn("[Self:", messages[0]["content"])
            self.assertNotIn("項目1", messages[0]["content"])

    def test_export_training_persists_only_explicit_pairs(self):
        pair = {
            "approved_by_user": True,
            "prompt": [{"role": "user", "content": "短く答えて"}],
            "completion": [{"role": "assistant", "content": "了解。"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reviewed.jsonl"
            self.assertEqual(tail.export_reviewed_pairs([pair], path), 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), pair)


if __name__ == "__main__":
    unittest.main()
