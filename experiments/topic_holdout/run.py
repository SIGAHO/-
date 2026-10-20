"""One-shot, disjoint human-corpus comparison with a frozen candidate."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.topic_corpus import run as prior
from companion_core.topic import TopicTracker
from companion_core.textmath import normalize_text

HERE = Path(__file__).resolve().parent
BASELINE = "3fad90f8e1384a594b32c55509a727d4e5263889"
BSD_REVISION = "050fd4241da458377c1ce26b2c31b0af0a20e444"
BSD_HASH = "8208c9160208c76659579d78d86c138d124c29b55e860b975eaaadfac8f12514"
SEED = "companion-unseen-v2-2026-10-21"
MODES = ("baseline", "candidate", "baseline_neutral", "candidate_neutral")


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def digest(value):
    return prior.sha(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())


def load_rows(archive, bsd_path):
    dialogues, splits = prior.read_archive(archive)
    old = json.loads((ROOT / "experiments/topic_corpus/manifest.json").read_text(encoding="utf-8"))
    excluded = {r["dialogue"] for r in old["rows"]}
    remaining = {"test": [name for name in splits["test"] if name not in excluded]}
    with patch.object(prior, "SEED", SEED):
        jm = prior.select_rows(dialogues, remaining)
    for row in jm:
        row["dataset"] = "jmultiwoz"
    raw = bsd_path.read_text(encoding="utf-8")
    if prior.sha(raw.encode()) != BSD_HASH:
        raise ValueError("BSD source hash mismatch")
    documents = [d for d in json.loads(raw) if d["original_language"] == "ja"]
    documents.sort(key=lambda d: prior.sha(f"{SEED}:{d['id']}".encode()))
    bsd = []
    for document in documents:
        for turn in document["conversation"]:
            bsd.append({"dataset": "bsd", "dialogue": document["id"], "turn_id": turn["no"],
                        "annotation_turn_id": None, "text": turn["ja_sentence"], "gold_domain": document["tag"]})
            if len(bsd) == 1000:
                break
        if len(bsd) == 1000:
            break
    if len(bsd) != 1000 or excluded & {r["dialogue"] for r in jm}:
        raise ValueError("Insufficient or overlapping holdout data")
    rows = jm + bsd
    manifest = {"seed": SEED, "previous_dialogues_excluded": sorted(excluded),
                "jmultiwoz_source": prior.SOURCE, "bsd_source": {"repository": "https://github.com/tsuruoka-lab/BSD", "revision": BSD_REVISION,
                    "test_json_normalized_sha256": BSD_HASH, "license": "CC-BY-NC-SA-4.0", "original_language": "ja"},
                "selection": "Fixed hash order of dialogue IDs, natural turn order, first 1000 per source; no model output or label filtering",
                "rows": [{k: v for k, v in r.items() if k != "text"} | {"text_sha256": prior.sha(r["text"].encode())} for r in rows]}
    return rows, manifest


def candidate_hashes():
    paths = sorted((ROOT / "src").rglob("*.py")) + [HERE / "run.py", HERE / "PROTOCOL.md"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): prior.sha(p.read_text(encoding="utf-8").encode()) for p in paths}


def baseline_type():
    module = types.ModuleType("companion_core._frozen_topic")
    module.__package__ = "companion_core"
    code = subprocess.check_output(["git", "show", f"{BASELINE}:src/companion_core/topic.py"], cwd=ROOT, text=True, encoding="utf-8")
    exec(compile(code, f"{BASELINE}:topic.py", "exec"), module.__dict__)
    return module.TopicTracker


def factories():
    baseline = baseline_type()
    class NeutralBaseline(baseline):
        DEFAULT_ALIASES = {}
        def _signature(self, text):
            # Disable only the old alias substitution; old clustering is intact.
            normalized = self._generic_pattern.sub(" ", normalize_text(text))
            return set(re.findall(r"[一-龯々]+|[ァ-ヺー]+|[a-z0-9_]+|[ぁ-ゖ]+", normalized)) - self.GENERIC_WORDS
    return {"baseline": baseline, "candidate": lambda: TopicTracker(policy="evidence"),
            "baseline_neutral": NeutralBaseline, "candidate_neutral": lambda: TopicTracker(policy="evidence", use_default_aliases=False)}


def probe(rows, factory):
    observations = []
    replay_passed = 0
    names = list(dict.fromkeys(r["dialogue"] for r in rows))
    for name in names:
        subset = [r for r in rows if r["dialogue"] == name]
        with patch("companion_core.core.TopicTracker", factory), patch("time.time", return_value=prior.NOW), patch("companion_core.time_engine.TimeEngine.now", return_value=prior.FIXTURE_DATE):
            predicted, replay_ok = prior.predict_texts([r["text"] for r in subset])
        replay_passed += replay_ok
        for row, observed in zip(subset, predicted):
            observations.append({k: v for k, v in row.items() if k != "text"} | observed)
    metrics = prior.score_transitions(observations)
    c = metrics["confusion"]
    metrics["within_domain_split_rate"] = prior.ratio(c["fp"], c["fp"] + c["tn"])
    return {"utterances": len(rows), "dialogues": len(names), "replay_passed": replay_passed,
            "invariants_passed": sum(all(r["invariants"].values()) for r in observations), "metrics": metrics}, observations


def assess(results):
    jm = results["jmultiwoz"]
    old, new = jm["baseline"]["metrics"], jm["candidate"]["metrics"]
    neutral_old, neutral_new = jm["baseline_neutral"]["metrics"], jm["candidate_neutral"]["metrics"]
    bsd = results["bsd"]
    return {
        "fewer_within_domain_splits": new["within_domain_split_rate"] < old["within_domain_split_rate"],
        "strict_switch_f1_improved": new["switch_f1"] > old["switch_f1"],
        "switch_recall_at_least_half": new["switch_recall"] >= 0.5,
        "dictionary_disabled_improves_splits": neutral_new["within_domain_split_rate"] < neutral_old["within_domain_split_rate"],
        "other_corpus_improves_splits": bsd["candidate"]["metrics"]["within_domain_split_rate"] < bsd["baseline"]["metrics"]["within_domain_split_rate"],
        "all_invariants_and_replays": all(r["invariants_passed"] == r["utterances"] and r["replay_passed"] == r["dialogues"] for dataset in results.values() for r in dataset.values()),
    }


def evaluate(rows, frozen):
    results, traces = {}, {m: [] for m in MODES}
    fs = factories()
    for dataset in ("jmultiwoz", "bsd"):
        subset = [r for r in rows if r["dataset"] == dataset]
        results[dataset] = {}
        for mode in MODES:
            result, observations = probe(subset, fs[mode])
            results[dataset][mode] = result
            traces[mode].extend(observations)
            print(f"{dataset}/{mode}: split={result['metrics']['within_domain_split_rate']:.3f}, F1={result['metrics']['switch_f1']}", flush=True)
    checks = assess(results)
    report = {"baseline_commit": BASELINE, "freeze": frozen, "utterances": len(rows), "training_examples": 0,
              "model_generated_texts": 0, "model_generated_labels": 0, "adoption_checks": checks,
              "candidate_passes_fixed_checks": all(checks.values()), "decision": "PASS" if all(checks.values()) else "REVISE",
              "general_semantic_accuracy": None, "results": results,
              "limits": ["Domain/scene labels are original human metadata, not conversational topic-boundary ground truth.",
                         "No full semantic generalization claim; BSD scenes may contain genuine subtopics.",
                         "No coefficient search or word additions after observing this holdout; no training."]}
    compact = []
    for i, row in enumerate(rows):
        compact.append({"dataset": row["dataset"], "dialogue": row["dialogue"], "turn_id": row["turn_id"],
                        "clusters": {m: traces[m][i]["predicted_cluster"] for m in MODES}})
    return report, compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bsd", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    rows, manifest = load_rows(args.archive, args.bsd)
    path = HERE / "manifest.json"
    if args.prepare:
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Refusing to replace a frozen sample")
        dump(path, manifest)
        print("Prepared 2000 human utterances; previous dialogue overlap = 0; no predictions")
        return 0
    if json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Frozen sample mismatch")
    freeze_path = HERE / "freeze.json"
    frozen = {"candidate": candidate_hashes(), "manifest_sha256": digest(manifest), "baseline": BASELINE, "janome": "0.5.0"}
    if args.freeze:
        if freeze_path.exists() and json.loads(freeze_path.read_text(encoding="utf-8")) != frozen:
            raise ValueError("Refusing to replace a frozen candidate")
        dump(freeze_path, frozen)
        print("Candidate and protocol frozen before holdout evaluation")
        return 0
    if json.loads(freeze_path.read_text(encoding="utf-8")) != frozen:
        raise ValueError("Candidate changed after freeze; cannot reuse this holdout for tuning")
    report, predictions = evaluate(rows, frozen)
    if candidate_hashes() != frozen["candidate"]:
        raise ValueError("Candidate mutated during evaluation")
    dump(HERE / "results.json", report)
    (HERE / "predictions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in predictions), encoding="utf-8", newline="\n")
    decision = ["# " + report["decision"], "", "事前固定の採用条件:", ""]
    decision.extend(f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in report["adoption_checks"].items())
    decision += ["", "判定は事前固定した代理指標の条件に限る。一般的な意味理解の証明ではない。",
                 "本文・教師文・正解ラベルのモデル生成なし。学習なし。元注釈・固定IDで再計算可能。", ""]
    (HERE / "DECISION.md").write_text("\n".join(decision), encoding="utf-8", newline="\n")
    print(json.dumps({"decision": report["decision"], "checks": report["adoption_checks"]}, indent=2))
    return 0 if report["candidate_passes_fixed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
