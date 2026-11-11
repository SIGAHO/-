import json
from pathlib import Path
import tempfile
import unittest

from breaktail_memory_pages import page_records


class MemoryPageTests(unittest.TestCase):
    def test_raw_pages_keep_turn_id_time_and_speakers(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            memory = root / "memory.jsonl"
            rows = [{"conversation_id": "session-a", "turn_id": f"turn-{index}",
                     "timestamp": f"2026-11-11T00:{index:02d}:00Z", "user_text": f"user-{index}",
                     "assistant_text": f"reply-{index}", "status": "complete"}
                    for index in range(12)]
            raw.write_text("".join(json.dumps(row) + "\n" for row in rows) + "bad-json\n", encoding="utf-8")
            first = page_records(memory, raw, "raw", 1)
            self.assertEqual((first["total"], first["start"], first["end"], first["page_count"]), (12, 1, 10, 2))
            self.assertEqual(first["invalid_rows"], 1)
            self.assertEqual(first["items"][0]["turn_id"], "turn-11")
            self.assertEqual(first["items"][0]["timestamp"], "2026-11-11T00:11:00Z")
            self.assertEqual([message["speaker"] for message in first["items"][0]["messages"]],
                             ["user", "assistant"])
            second = page_records(memory, raw, "raw", 2)
            self.assertEqual((second["start"], second["end"], second["has_next"]), (11, 12, False))
            with self.assertRaises(ValueError):
                page_records(memory, raw, "raw", 3)

    def test_interpretations_do_not_invent_raw_sources(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as directory:
            root = Path(directory)
            memory = root / "memory.jsonl"
            memory.write_text(json.dumps({"id": 1, "content": "unconfirmed", "created_at": "2026-11-11T00:00:00Z"}) + "\n",
                              encoding="utf-8")
            page = page_records(memory, root / "absent.jsonl", "interpretations", 1)
            self.assertEqual(page["total"], 1)
            self.assertIsNone(page["items"][0]["source_turn_id"])
            self.assertEqual(page["items"][0]["verification"], "unverified_interpretation")
            self.assertEqual(page_records(memory, root / "absent.jsonl", "raw", 1)["total"], 0)
            for value in (0, -1, "1", True):
                with self.assertRaises(ValueError):
                    page_records(memory, root / "absent.jsonl", "raw", value)


if __name__ == "__main__":
    unittest.main()

