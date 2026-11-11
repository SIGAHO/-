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

    def test_explicit_status_history_keeps_old_and_new_user_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            statements = [("session-a", "one", "未確認：望遠鏡修理"),
                          ("session-a", "two", "確認済み：望遠鏡修理"),
                          ("session-b", "three", "未確認：望遠鏡修理"),
                          ("session-a", "four", "「確認済み：薬局への質問」")]
            rows = [{"conversation_id": session, "turn_id": turn, "timestamp": f"2026-11-11T00:0{index}:00Z",
                     "user_text": text, "assistant_text": "ack", "status": "complete"}
                    for index, (session, turn, text) in enumerate(statements)]
            raw.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            page = page_records(root / "absent.jsonl", raw, "ledger", 1)
            self.assertEqual(page["total"], 3)
            old = next(item for item in page["items"] if item["turn_id"] == "one")
            new = next(item for item in page["items"] if item["turn_id"] == "two")
            other_session = next(item for item in page["items"] if item["turn_id"] == "three")
            self.assertFalse(old["is_latest"])
            self.assertEqual(old["superseded_by_turn_id"], "two")
            self.assertTrue(new["is_latest"])
            self.assertTrue(other_session["is_latest"])
            self.assertFalse(new["externally_verified"])


if __name__ == "__main__":
    unittest.main()

