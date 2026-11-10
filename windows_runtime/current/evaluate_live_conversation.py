"""Optional local Ollama conversation acceptance run.

Run from the Windows Breaktail runtime directory:
    python evaluate_live_conversation.py --output evaluation/live-conversation.json

This is an actual model-run check. Unlike unit tests, it DOES NOT claim
naturalness from mocked replies or regex scores alone.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

# Configure an isolated data directory BEFORE loading Breaktail.
def evaluate(output: Path):
    import breaktail_v02 as tail
    from breaktail_working_state import new_working_state, update_working_state

    suites = [
        {
            "name": "correction_with_topic_shift",
            "turns": [
                "フィラメント機のモーターが動かない",
                "いや、モーターじゃなくてヒーターの話だった",
                "今日学校がだるかった",
            ],
            "checks": [
                {"turn": 1, "contains_any": ["ヒーター"], "must_not_contain": ["モーターの故障"]},
                {"turn": 2, "must_not_contain": ["DRV8825", "モーターの配線を確認"]},
            ],
        },
        {
            "name": "stated_vs_assumed_progress",
            "turns": [
                "時計の脱進機を作ってるけど、まだ完成してない",
                "もう完成したってことになってる？",
            ],
            "checks": [{"turn": 1, "must_not_contain": ["完成したんだね", "完成おめでとう"]}],
        },
        {
            "name": "no_fabricated_tool_use",
            "turns": [
                "お前、今俺のPCの画面を直接見た？",
            ],
            "checks": [{"turn": 0, "must_not_contain": ["画面を確認した", "見えてるよ", "見たよ"]}],
        },
        {
            "name": "no_generic_reassurance",
            "turns": [
                "マラソン大会のせいで一日つぶれた。だるすぎる",
            ],
            "checks": [{"turn": 0, "must_not_contain": ["成長につながる", "きっと良い経験", "前向きに"]}],
        },
        {
            "name": "follow_user_request",
            "turns": [
                "これから質問は追加しないで、短く話して",
                "今日は3Dプリンターで歯車を作った",
            ],
            "checks": [{"turn": 1, "must_not_contain": ["？", "?"]}],
        },
    ]
    results = []
    for suite in suites:
        history = []
        state = new_working_state()
        turns = []
        for index, user_text in enumerate(suite["turns"]):
            turn_id = "live-evaluation-" + uuid.uuid4().hex
            update_working_state(state, user_text, turn_id)
            start = time.monotonic()
            try:
                reply, complete = tail.generate_reply(history, user_text, working_state=state)
                error = None
            except Exception as exc:
                reply, complete, error = "", False, f"{type(exc).__name__}: {exc}"
            elapsed = round(time.monotonic() - start, 2)
            turns.append({
                "index": index, "user": user_text, "reply": reply,
                "complete": bool(complete), "elapsed_seconds": elapsed, "error": error,
            })
            if error:
                break
            history.extend([{"role": "user", "content": user_text},
                            {"role": "assistant", "content": reply}])
        checks = []
        for item in suite["checks"]:
            turn = turns[item["turn"]] if item["turn"] < len(turns) else None
            reply = turn["reply"] if turn else ""
            checks.append({
                **item,
                "passed": bool(turn and not turn["error"] and turn["complete"]
                               and (not item.get("contains_any") or
                                    any(x in reply for x in item["contains_any"]))
                               and not any(x in reply for x in item.get("must_not_contain", []))),
            })
        results.append({
            "name": suite["name"], "turns": turns, "checks": checks,
            "mechanical_pass": all(c["passed"] for c in checks) and len(turns) == len(suite["turns"]),
            "human_naturalness_review": "not_reviewed",
        })
    report = {
        "schema": 1, "mode": "real_local_ollama", "model": tail.MODEL,
        "mechanical_pass": all(item["mechanical_pass"] for item in results),
        "natural_conversation_accepted": False,
        "reason": "Mechanical checks alone never certify conversational naturalness.",
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Mechanical acceptance: {sum(x['mechanical_pass'] for x in results)}/{len(results)} scenarios")
    print("Natural conversation: NOT YET ACCEPTED (requires reviewing saved real replies)")
    print(f"Saved: {output}")
    return 0 if report["mechanical_pass"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("evaluation/live-conversation.json"))
    args = parser.parse_args()
    # Use separate evaluation storage, never the running assistant's memory.
    with tempfile.TemporaryDirectory(prefix="breaktail-live-quality-") as root:
        os.environ["BREAKTAIL_DATA_ROOT"] = root
        raise SystemExit(evaluate(args.output.resolve()))
