import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import breaktail_raw_conversation as raw
import breaktail_teacher_store as store


class TeacherStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for obj, name, value in ((raw, "RAW_CONVERSATION_FILE", root / "raw.jsonl"),
                                  (raw, "RAW_CONVERSATION_LOCK_FILE", root / "raw.lock"),
                                  (store, "MODEL_TRACE_FILE", root / "trace.jsonl")):
            guard = patch.object(obj, name, value)
            guard.start()
            self.addCleanup(guard.stop)

    def _teach(self, db, conversation="conv", turn="turn"):
        self.assertTrue(raw.save_turn(conversation, turn, "質問", "元の返答", "complete"))
        return store.add_teach(conversation, turn, [{"role": "user", "content": "質問"}], "望む返答", db)

    def test_teach_persists_and_exports_only_active_approved_human_records(self):
        with tempfile.TemporaryDirectory() as temp:
            db, output = Path(temp) / "teacher.sqlite3", Path(temp) / "train.jsonl"
            result = self._teach(db)
            self.assertTrue(result["inserted"])
            self.assertEqual(store.export_training(output, db), 1)
            self.assertEqual(len(store.active_reply_teachers(db)), 1)  # reopen simulates restart
            self.assertTrue(store.revoke(result["teacher_id"], db))
            self.assertEqual(store.export_training(output, db), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "")

    def test_duplicate_provenance_and_unsaved_raw_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "teacher.sqlite3"
            first = self._teach(db)
            duplicate = store.add_teach("conv", "turn", [{"role": "user", "content": "質問"}], "望む返答", db)
            self.assertTrue(first["inserted"])
            self.assertFalse(duplicate["inserted"])
            with self.assertRaises(store.TeacherStoreError):
                store.add_teach("missing", "raw", [], "答え", db)
            with self.assertRaises(store.TeacherStoreError):
                store.add({"source_type": "human_style_sample", "input_context": [], "target_text": "文", "provenance": {}}, db)

    def test_synthetic_and_failed_v1_never_become_training_examples(self):
        with tempfile.TemporaryDirectory() as temp:
            db, output = Path(temp) / "teacher.sqlite3", Path(temp) / "train.jsonl"
            with self.assertRaises(store.TeacherStoreError):
                store.add({"source_type": "synthetic_candidate", "input_context": [], "target_text": "AI候補",
                           "provenance": {"kind": "model"}, "status": "active"}, db)
            self.assertEqual(store.export_training(output, db), 0)
            with self.assertRaises(store.TeacherStoreError):
                store.add({"source_type": "human_teacher", "input_context": [{"role": "user", "content": "質問"}],
                           "target_text": "FAILED_V1からコピーした文", "approved_at": "2026-10-20T12:00:00+09:00",
                           "source_conversation_id": "c", "source_turn_id": "t",
                           "provenance": {"kind": "raw_turn", "target_author": "human", "source": "FAILED_V1"}}, db)

    def test_reference_style_material_cannot_be_registered_as_reply_teacher(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "teacher.sqlite3"
            with self.assertRaises(store.TeacherStoreError):
                store.add({"source_type": "human_style_sample", "input_context": [],
                           "target_text": "あでもあれか", "provenance": {"target_author": "human"}}, db)
            self.assertEqual(store.export_training(Path(temp) / "train.jsonl", db), 0)

    def test_pre_grounding_generated_draft_cannot_become_teacher(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = {"event": "ollama_response", "response": {"message": {"content": "生成された未加工の文"}}}
            store.MODEL_TRACE_FILE.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
            raw.save_turn("c", "t", "質問", "Grounding後の別の文", "complete")
            with self.assertRaises(store.TeacherStoreError):
                store.add_teach("c", "t", [{"role": "user", "content": "質問"}], " 生成された 未加工の文 ", Path(temp) / "teacher.sqlite3")


if __name__ == "__main__":
    unittest.main()
