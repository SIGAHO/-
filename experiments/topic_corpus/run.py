"""Frozen human-corpus evaluation. No training, text generation, or LLM judging."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.runner import FIXTURE_DATE, NOW
from companion_core import CompanionCore
from companion_core.models import Status, SourceType
from companion_core.topic import TopicTracker

HERE = Path(__file__).resolve().parent
SOURCE = {
    "name": "JMultiWOZ 1.0",
    "repository": "https://github.com/nu-dialogue/jmultiwoz",
    "revision": "a78dd334b907e12318b76bb23d0a9ed1498b8d15",
    "archive_sha256": "283dea36f5abeea8f016fea2bd4df4dfba67a40f89c4600e47ed701c57ea2bc2",
    "license": "CC-BY-SA-4.0",
    "paper": "https://arxiv.org/abs/2403.17319",
    "authors": "Atsumoto Ohashi, Ryu Hirai, Shinya Iizuka, Ryuichiro Higashinaka",
    "text_provenance": "Human USER and human wizard; original corpus, not model inference outputs",
    "label_provenance": "Released SYSTEM-turn belief_state.general.active_domain; human-operated/annotated corpus state",
}
SEED = "companion-topic-2026-10-21-v1"
COUNT = 1000
DOMAINS = {"hotel", "restaurant", "attraction", "shopping", "taxi", "weather"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_archive(path):
    if sha(path.read_bytes()) != SOURCE["archive_sha256"]:
        raise ValueError("Archive hash differs from the pinned human corpus")
    # Read JSON only; never execute the upstream repository or extract paths.
    with zipfile.ZipFile(path) as archive:
        dialogues = json.loads(archive.read("JMultiWOZ_1.0/dialogues.json"))
        splits = json.loads(archive.read("JMultiWOZ_1.0/split_list.json"))
    return dialogues, splits


def select_rows(dialogues, splits, count=COUNT):
    """Selection depends on seed/IDs/turn order, never labels or predictions."""
    names = sorted(splits["test"], key=lambda name: sha(f"{SEED}:{name}".encode()))
    rows = []
    for name in names:
        turns = dialogues[name]["turns"]
        for i, turn in enumerate(turns):
            if turn["speaker"] != "USER":
                continue
            following = turns[i + 1] if i + 1 < len(turns) and turns[i + 1]["speaker"] == "SYSTEM" else None
            domain = None
            if following:
                domain = following.get("dialogue_state", {}).get("belief_state", {}).get("general", {}).get("active_domain")
            rows.append({"dialogue": name, "turn_id": turn["turn_id"], "text": turn["utterance"],
                         "annotation_turn_id": following["turn_id"] if following else None,
                         "gold_domain": domain if domain in DOMAINS else None})
            if len(rows) == count:
                return rows
    raise ValueError(f"Insufficient USER utterances: {len(rows)} < {count}")


def make_manifest(rows):
    return {"schema_version": 1, "source": SOURCE, "split": "test", "seed": SEED,
            "selection": "SHA256(seed:dialogue_name) order, natural USER-turn order, first 1000 instances; final dialogue may be truncated",
            "model_generated_texts": 0, "model_generated_labels": 0, "training_examples": 0,
            "rows": [{k: v for k, v in row.items() if k != "text"} | {"text_sha256": sha(row["text"].encode("utf-8"))} for row in rows]}


def topic_index(core):
    return next((i for i, topic in enumerate(core.topic.topics) if topic is core.topic.current()), None)


def semantic_snapshot(core):
    """Runtime-clock State is deliberately excluded: replay doesn't restore it."""
    return {"topics": [(t.label, sorted(t.signature), t.score) for t in core.topic.topics],
            "current": topic_index(core), "emotion": core.emotion.state.to_dict(),
            "loops": [(loop.text, loop.done) for loop in core.open_loops.loops],
            "memories": [(m.text, m.source.value, m.mentions) for m in core.memory.items]}


def predict_texts(texts):
    """The prediction path receives text only. Corpus labels cannot reach Core."""
    core = CompanionCore()
    observations = []
    for text in texts:
        context = core.handle(text)
        index = topic_index(core)
        emotions = core.emotion.state.to_dict()
        invariants = {
            "one_active_fact_per_key": all(sum(f.status == Status.ACTIVE for f in facts) == 1 for facts in core.state.history.values()),
            "no_assistant_fact_source": all(f.source != SourceType.ASSISTANT_GENERATED for f in core.state.active.values()),
            "memory_budget": sum(map(len, context["memory"])) <= 1200,
            "emotion_bounds": all((-1 if k == "valence" else 0) <= v <= 1 for k, v in emotions.items()),
            "context_focus": context["topic"] == (None if index is None else {"label": core.topic.current().label, "score": round(core.topic.current().score, 3)}),
        }
        observations.append({"predicted_cluster": index, "invariants": invariants})
    before = semantic_snapshot(core)
    core.replay()
    return observations, before == semantic_snapshot(core)


def ratio(a, b):
    return a / b if b else None


def score_transitions(rows):
    confusion = Counter(tp=0, fp=0, tn=0, fn=0)
    errors_by_domain = Counter()
    eligible = 0
    abstained = 0
    return_total = 0
    return_correct = 0
    previous = None
    last_cluster = {}
    for row in rows:
        if previous is None or previous["dialogue"] != row["dialogue"]:
            last_cluster = {}
            previous = None
        row["transition"] = None
        domain = row["gold_domain"]
        cluster = row["predicted_cluster"]
        if previous is not None and domain is not None and previous["gold_domain"] is not None:
            eligible += 1
            if cluster is None or previous["predicted_cluster"] is None:
                abstained += 1
            else:
                gold_switch = domain != previous["gold_domain"]
                predicted_switch = cluster != previous["predicted_cluster"]
                cell = ("tp" if predicted_switch else "fn") if gold_switch else ("fp" if predicted_switch else "tn")
                confusion[cell] += 1
                row["transition"] = {"corpus_domain_changed": gold_switch, "cluster_changed": predicted_switch, "cell": cell}
                if cell in {"fp", "fn"}:
                    errors_by_domain[f"{previous['gold_domain']}->{domain}:{cell}"] += 1
                if gold_switch and domain in last_cluster and last_cluster[domain] is not None:
                    return_total += 1
                    return_correct += cluster == last_cluster[domain]
        if domain is not None:
            last_cluster[domain] = cluster
        previous = row
    tp, fp, tn, fn = (confusion[k] for k in ("tp", "fp", "tn", "fn"))
    return {"eligible_transitions": eligible, "abstained": abstained, "scored_transitions": tp + fp + tn + fn,
            "coverage": ratio(tp + fp + tn + fn, eligible), "confusion": dict(confusion),
            "accuracy": ratio(tp + tn, tp + fp + tn + fn), "switch_precision": ratio(tp, tp + fp),
            "switch_recall": ratio(tp, tp + fn), "switch_f1": ratio(2 * tp, 2 * tp + fp + fn),
            "continuation_retention": ratio(tn, tn + fp),
            "always_continue_accuracy": ratio(tn + fp, tp + fp + tn + fn),
            "always_split_accuracy": ratio(tp + fn, tp + fp + tn + fn),
            "return_events": return_total, "return_correct": return_correct,
            "return_accuracy": ratio(return_correct, return_total), "proxy_errors_by_domain": dict(sorted(errors_by_domain.items()))}


def run(rows):
    output = []
    replay_checks = []
    for name in dict.fromkeys(row["dialogue"] for row in rows):
        subset = [row for row in rows if row["dialogue"] == name]
        # Fix metadata only. Topic features, coefficients and decisions are unchanged.
        with ExitStack() as stack:
            stack.enter_context(patch("time.time", return_value=NOW))
            stack.enter_context(patch("companion_core.time_engine.TimeEngine.now", return_value=FIXTURE_DATE))
            observed, replay_ok = predict_texts([row["text"] for row in subset])
        replay_checks.append({"dialogue": name, "passed": replay_ok})
        for row, observation in zip(subset, observed):
            output.append({k: v for k, v in row.items() if k != "text"} | observation | {"text_sha256": sha(row["text"].encode())})
    metrics = score_transitions(output)
    invariant_totals = {name: sum(row["invariants"][name] for row in output) for name in output[0]["invariants"]}
    report = {"schema_version": 1, "source": SOURCE, "model_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "src_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p.read_bytes()) for p in sorted((ROOT / "src").rglob("*.py"))},
              "evaluator_sha256": sha(Path(__file__).read_bytes()), "manifest_sha256": sha((HERE / "manifest.json").read_bytes()),
              "utterances": len(rows), "unique_texts": len({r["text"] for r in rows}), "dialogues": len(replay_checks),
              "domain_counts": dict(sorted(Counter(row["gold_domain"] or "unlabeled" for row in rows).items())),
              "model_generated_texts": 0, "model_generated_labels": 0, "training_examples": 0,
              "invariant_totals": invariant_totals, "replay_passed": sum(r["passed"] for r in replay_checks),
              "metrics": metrics, "decision": "REVISE", "adoption_allowed": False,
              "semantic_topic_accuracy": None,
              "limitations": ["Active task-domain changes are an external proxy, not human-annotated conversational topic boundaries.",
                              "Only USER utterances are input; wizard responses and all annotations are withheld from Core.",
                              "Travel-related task dialogue is not a broad everyday-conversation benchmark.",
                              "No manual relabeling or human adjudication of these 1000 rows has been performed.",
                              "This observed evaluation sample must not be repurposed for training or benchmark-specific tuning."]}
    return report, output, replay_checks


def decision_text(report, rows):
    m = report["metrics"]
    c = m["confusion"]
    lines = ["# REVISE", "", "汎用Topic方式として採用不可。この評価で本体の辞書・係数・正解ラベルは変更していない。", "",
             f"人間由来のUSER発話 {report['utterances']} 件、{report['dialogues']} 対話。異なる本文は {report['unique_texts']} 件。",
             "原データの6業務ドメインを代理指標として評価し、モデルが生成した教師文・教師ラベルは0件。訓練も0件。", "",
             f"- 遷移評価: {m['scored_transitions']}/{m['eligible_transitions']} 件。棄権 {m['abstained']} 件。",
             f"- 同じ業務ドメインの {c['tn'] + c['fp']} 遷移中、{c['fp']} 件で別クラスタ。継続保持率 {m['continuation_retention']:.2%}。",
             f"- 業務ドメイン変更 {c['tp'] + c['fn']} 件中、{c['tp']} 件でクラスタ変更。",
             f"- 変更検出: precision {m['switch_precision']:.2%} / recall {m['switch_recall']:.2%} / F1 {m['switch_f1']:.2%}。",
             f"- 代理遷移の一致率 {m['accuracy']:.2%}。常に継続する比較基準 {m['always_continue_accuracy']:.2%}。",
             f"- 元ラベル不明 {report['domain_counts'].get('unlabeled', 0)} 発話。AIによるラベル補完なし。",
             f"- 復帰イベント {m['return_events']} 件。0件なら復帰性能は判定不能。",
             f"- 不変条件は各 {report['utterances']} 件中 " + ", ".join(f"{k}={v}" for k, v in report['invariant_totals'].items()) + "。",
             f"- Replay: {report['replay_passed']}/{report['dialogues']} 対話（時計Stateの復元は対象外）。", "",
             "## 判断の限界", "",
             "これは業務ドメイン遷移との整合性であり、雑談の意味的な話題境界についての人手正解率ではない。",
             "同一ドメイン内に複数の話題があるため、これらの差分をすべて確定した意味理解の誤りと呼ばない。",
             "ただし現在の21件の回帰PASSだけでは、この外部データ上の大きな分裂傾向を検出できていなかった。",
             "不変条件の成功を意味理解の成功へ読み替えず、汎用性の採用判断はREVISEとする。", "",
             "次に必要なのは、別の未使用分野に対する人間の話題境界注釈と、分野辞書に依存しない比較器の検証。",
             "今回の評価済み1000発話を見て辞書・閾値を合わせず、教師データにも流用しない。", "",
             "## 人手確認用の差分参照（原文は元データから照合）", ""]
    for row in [r for r in rows if r.get("transition") and r["transition"]["cell"] in {"fp", "fn"}][:10]:
        lines.append(f"- {row['dialogue']} / USER turn {row['turn_id']} / annotation turn {row['annotation_turn_id']}: {row['transition']['cell']}, 原ドメイン={row['gold_domain']}, cluster={row['predicted_cluster']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Pinned upstream JMultiWOZ_1.0.zip; never uploaded")
    parser.add_argument("--prepare", action="store_true", help="Freeze the sample and source labels without running Core")
    args = parser.parse_args()
    dialogues, splits = read_archive(args.archive)
    rows = select_rows(dialogues, splits)
    manifest = make_manifest(rows)
    path = HERE / "manifest.json"
    if args.prepare:
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Refusing to replace a previously frozen evaluation sample")
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Frozen {len(rows)} human USER utterances; no predictions or training")
        return 0
    if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Source/sample mismatch; prepare a frozen manifest first")
    report, observed, replay = run(rows)
    (HERE / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "predictions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observed), encoding="utf-8")
    (HERE / "replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    (HERE / "DECISION.md").write_text(decision_text(report, observed), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("utterances", "dialogues", "domain_counts", "metrics", "invariant_totals", "replay_passed", "decision")}, ensure_ascii=False, indent=2))
    return 1  # A proxy-only study cannot grant general semantic adoption.


if __name__ == "__main__":
    raise SystemExit(main())
