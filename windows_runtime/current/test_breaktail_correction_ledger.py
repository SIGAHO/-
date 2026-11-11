import json
from pathlib import Path
import tempfile
import unittest

from breaktail_correction_ledger import commit, history, preview


class CorrectionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.raw = root / "raw.jsonl"
        self.ledger = root / "corrections.jsonl"
        turns = [("conversation-a", "old-turn-0001", "The shop is east."),
                 ("conversation-a", "new-turn-0002", "Correction: the shop is west."),
                 ("conversation-a", "next-turn-0003", "It moved north."),
                 ("conversation-b", "other-turn-0004", "The shop is south.")]
        self.raw.write_text("".join(json.dumps({"conversation_id": session, "turn_id": identity,
                                                "timestamp": f"2026-11-12T00:0{index}:00Z",
                                                "user_text": text, "assistant_text": "ack",
                                                "status": "complete"}) + "\n"
                                   for index, (session, identity, text) in enumerate(turns)), encoding="utf-8")

    def test_explicit_links_keep_both_sources_and_latest_without_certifying_fact(self):
        first = preview(self.raw, "shop location", "old-turn-0001", "new-turn-0002")
        self.assertFalse(self.ledger.exists())
        self.assertEqual(first["old"]["text"], "The shop is east.")
        self.assertEqual(first["new"]["text"], "Correction: the shop is west.")
        saved = commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
                       first["old"]["sha256"], first["new"]["sha256"])
        self.assertFalse(saved["already_recorded"])
        repeat = commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
                        first["old"]["sha256"], first["new"]["sha256"])
        self.assertTrue(repeat["already_recorded"])
        second = preview(self.raw, "shop location", "new-turn-0002", "next-turn-0003")
        commit(self.raw, self.ledger, "shop location", "new-turn-0002", "next-turn-0003",
               second["old"]["sha256"], second["new"]["sha256"])
        report = history(self.raw, self.ledger, "shop location", "old-turn-0001")
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["latest_turn_id"], "next-turn-0003")
        self.assertEqual(report["items"][0]["old_text"], "The shop is east.")
        self.assertEqual(report["items"][0]["new_text"], "Correction: the shop is west.")
        self.assertFalse(report["items"][1]["external_verification"])
        self.assertEqual(len(self.ledger.read_text(encoding="utf-8").splitlines()), 2)

    def test_wrong_hash_branch_and_cross_session_are_rejected(self):
        checked = preview(self.raw, "shop location", "old-turn-0001", "new-turn-0002")
        with self.assertRaises(ValueError):
            commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
                   "0" * 64, checked["new"]["sha256"])
        self.assertFalse(self.ledger.exists())
        commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
               checked["old"]["sha256"], checked["new"]["sha256"])
        branch = preview(self.raw, "shop location", "old-turn-0001", "next-turn-0003")
        with self.assertRaises(ValueError):
            commit(self.raw, self.ledger, "shop location", "old-turn-0001", "next-turn-0003",
                   branch["old"]["sha256"], branch["new"]["sha256"])
        with self.assertRaises(ValueError):
            preview(self.raw, "shop location", "new-turn-0002", "other-turn-0004")
        with self.assertRaises(ValueError):
            preview(self.raw, "shop location", "new-turn-0002", "old-turn-0001")
        self.assertEqual(history(self.raw, self.ledger, "shop location", "other-turn-0004")["count"], 0)

    def test_changed_raw_is_not_reported_as_current_value(self):
        checked = preview(self.raw, "shop location", "old-turn-0001", "new-turn-0002")
        commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
               checked["old"]["sha256"], checked["new"]["sha256"])
        rows = [json.loads(line) for line in self.raw.read_text(encoding="utf-8").splitlines()]
        rows[1]["user_text"] = "Changed after registration."
        self.raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        report = history(self.raw, self.ledger, "shop location", "old-turn-0001")
        self.assertEqual(report["count"], 1)
        self.assertIsNone(report["latest_turn_id"])
        self.assertIsNone(report["latest_text"])
        self.assertFalse(report["items"][0]["sources_available"])

    def test_idempotent_retry_rejects_tampered_existing_record(self):
        checked = preview(self.raw, "shop location", "old-turn-0001", "new-turn-0002")
        commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
               checked["old"]["sha256"], checked["new"]["sha256"])
        record = json.loads(self.ledger.read_text(encoding="utf-8"))
        record["new_source_sha256"] = "0" * 64
        self.ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "再確認できません"):
            commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
                   checked["old"]["sha256"], checked["new"]["sha256"])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_corrupt_topic_key_fails_closed(self):
        checked = preview(self.raw, "shop location", "old-turn-0001", "new-turn-0002")
        commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
               checked["old"]["sha256"], checked["new"]["sha256"])
        record = json.loads(self.ledger.read_text(encoding="utf-8"))
        record["key"] = "different topic"
        self.ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "破損"):
            history(self.raw, self.ledger, "shop location", "old-turn-0001")
        with self.assertRaisesRegex(ValueError, "破損"):
            commit(self.raw, self.ledger, "shop location", "old-turn-0001", "new-turn-0002",
                   checked["old"]["sha256"], checked["new"]["sha256"])
        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

