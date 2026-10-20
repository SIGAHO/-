"""Reuse the fixed evaluator on new, never-scored development dialogues."""
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

    def load_development(archive, bsd_path):
        dialogues, splits = original_read(archive)
        with patch.object(evaluation.prior, "read_archive", return_value=(dialogues, {"test": splits["dev"]})):
            rows, manifest = original_load(archive, bsd_path)
        manifest["jmultiwoz_split"] = "dev (unused by the baseline and first candidate)"
        manifest["bsd_source"]["partition"] = "dev (unused by the first candidate)"
        return rows, manifest

    def hashes():
        return original_hashes() | {"experiments/topic_holdout/run.py": evaluation.prior.sha(Path(evaluation.__file__).read_text(encoding="utf-8").encode())}

    with patch.object(evaluation, "HERE", Path(__file__).resolve().parent), \
         patch.object(evaluation, "SEED", "companion-unseen-dev-v3-2026-10-21"), \
         patch.object(evaluation, "BSD_HASH", "5a2d128c7b7d6b01b0cefd2a25ae9d06bef77885df640acbc67cd7e90fd717ff"), \
         patch.object(evaluation, "load_rows", load_development), \
         patch.object(evaluation, "candidate_hashes", hashes):
        return evaluation.main()


if __name__ == "__main__":
    raise SystemExit(main())
