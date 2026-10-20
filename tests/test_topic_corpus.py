"""Plumbing fixtures below are ASCII test records, never language training data."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.topic_corpus import run as corpus


class ExternalCorpusTests(unittest.TestCase):
    def test_frozen_bundle_has_1000_matching_source_records_and_recomputable_scores(self):
        manifest = json.loads((corpus.HERE / "manifest.json").read_text(encoding="utf-8"))
        report = json.loads((corpus.HERE / "results.json").read_text(encoding="utf-8"))
        predictions = [json.loads(line) for line in (corpus.HERE / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(manifest["rows"]), 1000)
        self.assertEqual(len(predictions), 1000)
        self.assertEqual(len({(r["dialogue"], r["turn_id"]) for r in predictions}), 1000)
        for reference, predicted in zip(manifest["rows"], predictions):
            self.assertTrue(all(predicted[k] == v for k, v in reference.items()))
            self.assertNotIn("text", predicted)
        self.assertEqual(corpus.score_transitions(copy.deepcopy(predictions)), report["metrics"])
        self.assertEqual(manifest["source"], corpus.SOURCE)
        self.assertFalse(report["adoption_allowed"])

    def test_selection_is_deterministic_and_independent_of_labels(self):
        dialogues = {name: {"turns": [
            {"turn_id": 0, "speaker": "USER", "utterance": name},
            {"turn_id": 1, "speaker": "SYSTEM", "utterance": "excluded-response", "dialogue_state": {"belief_state": {"general": {"active_domain": domain}}}},
        ]} for name, domain in (("record-a", "hotel"), ("record-b", "taxi"), ("record-c", "weather"))}
        split = {"test": list(dialogues), "train": ["not-used"]}
        first = corpus.select_rows(dialogues, split, count=2)
        altered = copy.deepcopy(dialogues)
        for d in altered.values():
            d["turns"][1]["dialogue_state"]["belief_state"]["general"]["active_domain"] = "shopping"
        second = corpus.select_rows(altered, split, count=2)
        self.assertEqual([(r["dialogue"], r["turn_id"], r["text"]) for r in first], [(r["dialogue"], r["turn_id"], r["text"]) for r in second])
        self.assertEqual(first, corpus.select_rows(dialogues, split, count=2))
        self.assertTrue(all(row["annotation_turn_id"] == 1 for row in first))

    def test_missing_annotation_is_not_invented(self):
        rows = corpus.select_rows({"record": {"turns": [{"turn_id": 0, "speaker": "USER", "utterance": "record-text"}]}}, {"test": ["record"]}, count=1)
        self.assertIsNone(rows[0]["gold_domain"])
        self.assertIsNone(rows[0]["annotation_turn_id"])

    def test_manifest_retains_source_label_and_hash_but_no_text(self):
        text = "record-text"
        manifest = corpus.make_manifest([{"dialogue": "record", "turn_id": 0, "text": text, "gold_domain": "hotel", "annotation_turn_id": 1}])
        self.assertNotIn("text", manifest["rows"][0])
        self.assertEqual(manifest["rows"][0]["gold_domain"], "hotel")
        self.assertEqual(manifest["rows"][0]["text_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(manifest["model_generated_labels"], 0)
        self.assertEqual(manifest["training_examples"], 0)

    def test_unpinned_archive_is_rejected(self):
        path = Mock()
        path.read_bytes.return_value = b"not-the-upstream-dataset"
        with self.assertRaises(ValueError):
            corpus.read_archive(path)

    def test_transition_confusion_return_and_dialogue_boundaries(self):
        rows = [{"dialogue": "a", "gold_domain": domain, "predicted_cluster": cluster} for domain, cluster in (("hotel", 0), ("hotel", 1), ("taxi", 1), ("taxi", 2), ("hotel", 1), ("hotel", 1))]
        rows.append({"dialogue": "b", "gold_domain": "weather", "predicted_cluster": 0})
        scores = corpus.score_transitions(rows)
        self.assertEqual(scores["confusion"], {"tp": 1, "fp": 2, "tn": 1, "fn": 1})
        self.assertEqual(scores["eligible_transitions"], 5)
        self.assertEqual(scores["switch_f1"], 0.4)
        self.assertEqual(scores["return_events"], 1)
        self.assertEqual(scores["return_correct"], 1)
        self.assertIsNone(rows[-1]["transition"])

    def test_missing_labels_and_abstentions_are_not_counted_as_passes(self):
        rows = [{"dialogue": "a", "gold_domain": domain, "predicted_cluster": cluster} for domain, cluster in (("hotel", None), ("hotel", 0), (None, 0), ("taxi", 1), ("taxi", 1))]
        scores = corpus.score_transitions(rows)
        self.assertEqual(scores["eligible_transitions"], 2)
        self.assertEqual(scores["abstained"], 1)
        self.assertEqual(scores["scored_transitions"], 1)
        self.assertEqual(scores["coverage"], 0.5)
        self.assertIsNone(scores["switch_precision"])

    def test_annotation_is_never_given_to_prediction_path(self):
        rows = [{"dialogue": "record", "turn_id": i, "annotation_turn_id": i + 1, "text": text, "gold_domain": domain} for i, text, domain in ((0, "input-a", "hotel"), (2, "input-b", "taxi"))]
        observed = [{"predicted_cluster": 0, "invariants": {"check": True}}, {"predicted_cluster": 0, "invariants": {"check": True}}]
        with patch.object(corpus, "predict_texts", return_value=(observed, True)) as predictor:
            report, output, _ = corpus.run(rows)
        predictor.assert_called_once_with(["input-a", "input-b"])
        self.assertEqual(report["training_examples"], 0)
        self.assertIsNone(report["semantic_topic_accuracy"])
        self.assertFalse(report["adoption_allowed"])
        self.assertTrue(all("text" not in r for r in output))


if __name__ == "__main__":
    unittest.main()
