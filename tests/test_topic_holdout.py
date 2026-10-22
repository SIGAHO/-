"""Audit published evidence, not generated Japanese teacher examples."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.topic_holdout import run as holdout


class HoldoutIntegrityTests(unittest.TestCase):
    def test_manifests_are_disjoint_and_predictions_recompute_metrics(self):
        root = holdout.ROOT / "experiments"
        original = json.loads((root / "topic_corpus/manifest.json").read_text(encoding="utf-8"))
        used = {("jmultiwoz", r["dialogue"]) for r in original["rows"]}
        for name in ("topic_holdout", "topic_holdout_v2", "topic_holdout_v3"):
            directory = root / name
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
            trace = [json.loads(line) for line in (directory / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
            rows = manifest["rows"]
            self.assertEqual(len(rows), 2000)
            self.assertEqual(len(trace), 2000)
            identities = {(r["dataset"], r["dialogue"]) for r in rows}
            self.assertFalse(used & identities)
            used |= identities
            self.assertEqual(report["freeze"]["manifest_sha256"], holdout.digest(manifest))
            self.assertEqual(report["training_examples"], 0)
            self.assertEqual(report["model_generated_labels"], 0)
            self.assertEqual(report["model_generated_texts"], 0)
            for row, prediction in zip(rows, trace):
                self.assertNotIn("text", row)
                for key in ("dataset", "dialogue", "turn_id"):
                    self.assertEqual(row[key], prediction[key])
            for dataset in ("jmultiwoz", "bsd"):
                self.assertEqual(sum(r["dataset"] == dataset for r in rows), 1000)
                for mode in holdout.MODES:
                    observations = [dict(r, predicted_cluster=p["clusters"][mode]) for r, p in zip(rows, trace) if r["dataset"] == dataset]
                    metrics = holdout.prior.score_transitions(observations)
                    confusion = metrics["confusion"]
                    metrics["within_domain_split_rate"] = holdout.prior.ratio(confusion["fp"], confusion["fp"] + confusion["tn"])
                    self.assertEqual(metrics, report["results"][dataset][mode]["metrics"])
            checks = holdout.assess(report["results"])
            self.assertEqual(checks, report["adoption_checks"])
            self.assertEqual(all(checks.values()), name == "topic_holdout_v3")

    def test_prediction_receives_text_only(self):
        rows = [dict(dataset="probe", dialogue="a", turn_id=0, text="input-a", gold_domain="private-label")]
        predictions = [dict(predicted_cluster=0, invariants={"check": True})]
        with patch.object(holdout.prior, "predict_texts", return_value=(predictions, True)) as predictor:
            holdout.probe(rows, lambda: None)
        predictor.assert_called_once_with(["input-a"])

    def test_recall_gate_is_not_waived_when_fragmentation_improves(self):
        report = json.loads((holdout.ROOT / "experiments/topic_holdout_v3/results.json").read_text(encoding="utf-8"))
        altered = copy.deepcopy(report["results"])
        altered["jmultiwoz"]["candidate"]["metrics"]["switch_recall"] = 0.499
        checks = holdout.assess(altered)
        self.assertFalse(checks["switch_recall_at_least_half"])
        self.assertFalse(all(checks.values()))

    def test_frozen_sources_match_preserved_candidates(self):
        root = holdout.ROOT
        for name, snapshot in (("topic_holdout", "v1_snapshot"), ("topic_holdout_v2", "snapshot"), ("topic_holdout_v3", None)):
            directory = root / "experiments" / name
            frozen = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
            for relative, expected in frozen["candidate"].items():
                path = root / relative
                if snapshot and relative in ("src/companion_core/topic.py", "src/companion_core/topic_evidence.py"):
                    path = directory / snapshot / (Path(relative).name + ".txt")
                # Historical candidate hashes remain immutable as live Core evolves.
                archived = root / "experiments/frozen_core" / (Path(relative).name + ".txt")
                if relative.startswith("src/companion_core/") and archived.exists():
                    path = archived
                self.assertEqual(holdout.prior.sha(path.read_text(encoding="utf-8").encode()), expected, relative)


if __name__ == "__main__":
    unittest.main()
