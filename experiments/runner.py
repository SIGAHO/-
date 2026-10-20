"""Shared, deterministic behavioral evaluator and admission gate (stdlib only)."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from companion_core import CompanionCore
from companion_core.models import SourceType, Scope, Status
from companion_core.state import StateEngine
from companion_core.correction import CorrectionEngine
from companion_core.topic import TopicTracker
from companion_core.open_loops import OpenLoopTracker
from companion_core.memory import MemoryEngine
from companion_core.emotion import EmotionEngine

SUITES = ("state", "correction", "topic", "open_loops", "memory", "emotion")
FIXTURE_DATE = datetime(2026, 10, 21, 9, tzinfo=timezone(timedelta(hours=9)))
NOW = FIXTURE_DATE.timestamp()


def source(value):
    return SourceType(value)


def observe(suite, case):
    """Adapters call actual public core methods, without reimplementing their rules."""
    if suite == "state":
        if "turns" in case:
            core = CompanionCore()
            for turn in case["turns"]:
                if turn.get("assistant"):
                    core.record_assistant_output(turn["text"])
                else:
                    core.handle(turn["text"], correction_key=turn.get("key"))
            keys = case.get("keys", [])
            return {"values": {k: core.state.active[k].value for k in keys if k in core.state.active}}
        engine = StateEngine()
        accepted = []
        for op in case["operations"]:
            if op["op"] == "correct":
                engine.correct(op["key"], op["value"], op.get("old"))
                accepted.append(True)
            else:
                accepted.append(engine.propose(op["key"], op["value"], source(op["source"]), Scope(op.get("scope", "session"))))
        return {"accepted": accepted,
                "values": {k: v.value for k, v in engine.active.items()},
                "sources": {k: v.source.value for k, v in engine.active.items()},
                "scopes": {k: v.scope.value for k, v in engine.active.items()},
                "blocked": {k: sorted(v) for k, v in engine.blocked.items()},
                "history": {k: [x.status.value for x in v] for k, v in engine.history.items()},
                "active_history_count": {k: sum(x.status == Status.ACTIVE for x in v) for k, v in engine.history.items()},
                "linked": {k: all(a.superseded_by == b.id for a, b in zip(v, v[1:])) for k, v in engine.history.items()}}
    if suite == "correction":
        found = CorrectionEngine().detect(case["text"])
        return {"corrections": [vars(c) for c in found], "count": len(found)}
    if suite == "topic":
        engine = TopicTracker()
        steps = []
        for text in case["texts"]:
            selected = engine.update(text)
            index = lambda t: next((i for i, x in enumerate(engine.topics) if x is t), None)
            steps.append({"selected": index(selected), "current": index(engine.current()), "count": len(engine.topics)})
        return {"steps": steps}
    if suite == "open_loops":
        engine = OpenLoopTracker()
        steps = []
        for text in case["texts"]:
            engine.observe(text)
            steps.append({"active": [x.text for x in engine.active()], "done": sum(x.done for x in engine.loops), "total": len(engine.loops)})
        return {"steps": steps}
    if suite == "memory":
        engine = MemoryEngine()
        accepted = []
        for spec in case["items"]:
            before = len(engine.items)
            accepted.append(engine.add(spec["text"], source(spec.get("source", "user_statement")), spec.get("importance", 0.5)))
            if len(engine.items) > before:
                item = engine.items[-1]
                item.created_at = NOW - spec.get("age_days", 0) * 86400
                item.mentions = spec.get("mentions", 1)
                item.status = Status(spec.get("status", "active"))
        if "archive" in case:
            engine.archive_old(now=NOW, **case["archive"])
        got = engine.retrieve(case.get("query", ""), **case.get("retrieve", {}))
        return {"accepted": accepted, "ranked": [x.text for x in got], "cost": sum(len(x.text) for x in got),
                "count": len(engine.items), "mentions": [x.mentions for x in engine.items],
                "importance": [x.importance for x in engine.items], "status": [x.status.value for x in engine.items]}
    if suite == "emotion":
        engine = EmotionEngine()
        initial = engine.state.to_dict()
        states = [initial]
        for text in case["texts"]:
            states.append(engine.observe_user(text).to_dict())
        return {"states": states, "delta": {k: states[-1][k] - initial[k] for k in initial},
                "max_step": max((abs(b[k] - a[k]) for a, b in zip(states, states[1:]) for k in initial), default=0),
                "bounded": all((-1 if k == "valence" else 0) <= v <= 1 for s in states for k, v in s.items()),
                "profile": dict(engine.user_profile)}
    raise ValueError(f"Unknown suite: {suite}")


def lookup(data, path):
    for part in path.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def evaluate(observed, check):
    actual = lookup(observed, check["path"])
    expected = lookup(observed, check["other"]) if "other" in check else check["value"]
    op = check["op"]
    if op == "eq":
        passed = actual == expected
    elif op == "ne":
        passed = actual != expected
    elif op == "gt":
        passed = actual > expected
    elif op == "ge":
        passed = actual >= expected
    elif op == "lt":
        passed = actual < expected
    elif op == "le":
        passed = actual <= expected
    elif op == "range":
        passed = expected[0] <= actual <= expected[1]
    elif op == "contains":
        passed = expected in actual
    else:
        raise ValueError(f"Unknown comparison: {op}")
    return {**check, "actual": actual, "expected": expected, "passed": passed}


def provenance(suite):
    paths = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__), ROOT / "experiments" / suite / "cases.jsonl", ROOT / "experiments" / suite / "hypothesis.md"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run_suite(suite, write=True):
    directory = ROOT / "experiments" / suite
    cases = [json.loads(line) for line in (directory / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cases) < 10 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("At least ten uniquely identified cases required")
    results = []
    for case in cases:
        if not case.get("checks") or not case.get("reason"):
            raise ValueError(f"Missing behavioral oracle/reason: {case['id']}")
        result = {"id": case["id"], "reason": case["reason"], "critical": case.get("critical", False)}
        try:
            # Fixed time/IDs affect metadata only. No engine rules are patched.
            with ExitStack() as stack:
                stack.enter_context(patch("time.time", return_value=NOW))
                stack.enter_context(patch("uuid.uuid4", side_effect=(uuid.UUID(int=i) for i in range(1, 10000))))
                stack.enter_context(patch("companion_core.time_engine.TimeEngine.now", return_value=FIXTURE_DATE))
                result["observed"] = observe(suite, case)
                result["checks"] = [evaluate(result["observed"], c) for c in case["checks"]]
            result["passed"] = all(c["passed"] for c in result["checks"])
        except Exception as exc:
            result.update(passed=False, error=f"{type(exc).__name__}: {exc}")
        results.append(result)
    passed = sum(r["passed"] for r in results)
    errors = any("error" in r for r in results)
    # Conservative admission: every specified behavior must pass. No xfail waiver.
    decision = "REJECT" if passed == 0 else "REVISE" if passed < len(results) else "PASS"
    report = {"schema_version": 1, "suite": suite, "fixture_time": FIXTURE_DATE.isoformat(),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "sha256": provenance(suite), "total": len(results), "passed": passed,
              "pass_rate": passed / len(results), "decision": decision, "adoption_allowed": decision == "PASS",
              "execution_errors": errors, "cases": results}
    if write:
        (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        failures = [r for r in results if not r["passed"]]
        lines = [f"# {decision}", "", f"{passed}/{len(results)} cases passed ({report['pass_rate']:.1%}).", "",
                 "採用条件: 全ケース成功、実行エラー0件。critical は権限・訂正・曖昧性などの必須不変条件。",
                 "PASS はこの有限ケース集合での仮説支持であり、理論の普遍的正しさの証明ではない。", "",
                 "採用可（別途統合・回帰検証が必要）。" if decision == "PASS" else "採用不可。失敗する振る舞いを修正し、同じケース集合で再実験すること。",
                 "本実験は既存本体を評価するだけで、本体の変更・新理論の統合は行わない。", "", "## 失敗と理由", ""]
        for r in failures:
            lines.append(f"- `{r['id']}`: {r['reason']}")
            if "error" in r:
                lines.append(f"  - 実行エラー（振る舞いの反証とは区別）: {r['error']}")
            for c in r.get("checks", []):
                if not c["passed"]:
                    lines.append(f"  - `{c['path']}`: 実測 {c['actual']!r}; 期待 `{c['op']}` {c['expected']!r}")
        if not failures:
            lines.append("- なし。未知表現・実会話・長期系列への一般化は未検証。")
        lines += ["", "結果の入力・本体・評価器の SHA-256 は results.json に保存。source_commit は実行時 HEAD。", ""]
        (directory / "DECISION.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main(suite=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="Evaluate without replacing evidence files")
    args = parser.parse_args()
    reports = [run_suite(name, not args.no_write) for name in ([suite] if suite else SUITES)]
    for r in reports:
        print(f"{r['suite']}: {r['passed']}/{r['total']} {r['decision']}")
    return 2 if any(r["execution_errors"] for r in reports) else 1 if any(not r["adoption_allowed"] for r in reports) else 0
