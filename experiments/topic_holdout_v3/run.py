"""An additional untouched partition; the partition name never implies training."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.topic_holdout import run as evaluation


def main():
    original_load = evaluation.load_rows
    original_read = evaluation.prior.read_archive
    original_hashes = evaluation.candidate_hashes

    def load_unused(archive, bsd_path):
        dialogues, splits = original_read(archive)
        with patch.object(evaluation.prior, "read_archive", return_value=(dialogues, {"test": splits["train"]})):
            rows, manifest = original_load(archive, bsd_path)
        used = set()
        for directory in ("topic_corpus", "topic_holdout", "topic_holdout_v2"):
            source = json.loads((ROOT / "experiments" / directory / "manifest.json").read_text(encoding="utf-8"))
            used.update((r.get("dataset", "jmultiwoz"), r["dialogue"]) for r in source["rows"])
        if used & {(r["dataset"], r["dialogue"]) for r in rows}:
            raise ValueError("A dialogue was previously evaluated")
        manifest["jmultiwoz_split"] = "upstream train, untouched here, EVALUATION ONLY"
        manifest["bsd_source"]["partition"] = "upstream train, untouched here, EVALUATION ONLY"
        manifest["earlier_dialogue_overlap"] = 0
        return rows, manifest

    def hashes():
        return original_hashes() | {"experiments/topic_holdout/run.py": evaluation.prior.sha(Path(evaluation.__file__).read_text(encoding="utf-8").encode())}

    with patch.object(evaluation, "HERE", Path(__file__).resolve().parent), \
         patch.object(evaluation, "SEED", "companion-additional-unseen-v4-2026-10-21"), \
         patch.object(evaluation, "BSD_HASH", "4e22ecba6a193e5980d93ca92d0ae050ab1663593df074e610edc8407b1a4020"), \
         patch.object(evaluation, "load_rows", load_unused), \
         patch.object(evaluation, "candidate_hashes", hashes):
        return evaluation.main()


if __name__ == "__main__":
    raise SystemExit(main())
