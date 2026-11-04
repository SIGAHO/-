"""Compare the historical Gemma→Qwen route with the Qwen-only reply path.

Uses a synthetic memory record plus held-out prompts, writes only a temporary memory
file, and never touches the live web session. Runs historical two-model cases first,
then Qwen-only cases consecutively so Ollama can keep Qwen warm for timing.
"""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import traceback
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import breaktail_v02 as after

ROOT = Path(__file__).resolve().parent
BACKUP = ROOT / "breaktail_v02.py.bak_qwen_migration_20261010"
TRANSFER_SET = Path(__file__).resolve().parent / "resources" / "eval-transfer.jsonl"
FIXTURE = "テスト用の保存記憶: ユーザーは返答を『要点、その次に注意点』の順で短くまとめるのを好む。"
HISTORY = [{"role": "user", "content": "次からその順番でまとめてほしい。"}]
CURRENT = "あの順番ってどんな形だっけ？"


def load_before():
    loader = SourceFileLoader("breaktail_v02_before", str(BACKUP))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.MODEL = "gemma3:12b"
    return module


def run_condition(label, module, memory_file, history, current, unload_on_second_call=True):
    module.MEMORY_FILE = memory_file
    if label == "after_qwen":
        module.MODEL = "qwen2.5:14b"
    call_count = 0
    metrics = []

    def call(messages, options, timeout, schema=None):
        nonlocal call_count
        call_count += 1
        # The pre-migration route used Gemma for the user-facing answer and
        # Qwen for the extraction call. The backed-up core predates that
        # route split, so reproduce the historical two-model configuration
        # here without changing either the backup or the live application.
        routed_model = (
            ("gemma3:12b" if call_count == 1 else "qwen2.5:14b")
            if label == "before_gemma_qwen"
            else module.MODEL
        )
        payload = {
            "model": routed_model,
            "messages": messages,
            "stream": False,
            "keep_alive": 0 if unload_on_second_call and call_count >= 2 else "10m",
            "options": {"num_ctx": module.NUM_CTX, **options},
        }
        if schema is not None:
            payload["format"] = schema
        request = urllib.request.Request(
            module.OLLAMA_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        metrics.append({
            "call": "reply" if call_count == 1 else "memory_scene_extraction",
            "model": routed_model,
            "wall_seconds": round(time.perf_counter() - started, 2),
            "total_duration_ns": result.get("total_duration"),
            "load_duration_ns": result.get("load_duration"),
            "prompt_eval_count": result.get("prompt_eval_count"),
            "eval_count": result.get("eval_count"),
        })
        return result

    module.call_ollama = call
    started = time.perf_counter()
    try:
        reply, complete = module.generate_reply(history, current)
        extraction, scene = module.extract_interpretation(current, None)
        return {
            "model": module.MODEL,
            "reply": reply,
            "complete": complete,
            "extraction_memory_candidate": extraction,
            "scene": scene,
            "total_seconds": round(time.perf_counter() - started, 2),
            "calls": metrics,
            "retrieved_test_memory": module.retrieve_relevant_memories("\n".join([message["content"] for message in history if message.get("role") == "user"] + [current])) if hasattr(module, "retrieve_relevant_memories") else [],
        }
    except Exception as error:
        return {"model": module.MODEL, "error": str(error), "traceback": traceback.format_exc(), "total_seconds": round(time.perf_counter() - started, 2), "calls": metrics}


def main():
    before = load_before()
    after.MEMORY_FILE = ROOT / ".migration-test-memory.tmp"
    cases = [{
        "id": "synthetic-memory-continuity",
        "history": HISTORY,
        "current": CURRENT,
        "memory": FIXTURE,
        "rubric": ["保存記憶の順序を思い出す", "無関係な話題へ飛ばない"],
    }]
    cases.extend({
        "id": item["id"],
        "history": item["messages"][:-1],
        "current": item["messages"][-1]["content"],
        "memory": "",
        "rubric": item.get("rubric", []),
    } for line in TRANSFER_SET.read_text(encoding="utf-8").splitlines() if line.strip() for item in [json.loads(line)])
    try:
        comparisons = [{
                "id": case["id"],
                "history": case["history"],
                "current_user_message": case["current"],
                "rubric": case["rubric"],
                "before_gemma_qwen": None,
                "after_qwen": None,
            } for case in cases]
        # Run each route as a block. If Gemma and Qwen are interleaved per
        # prompt, Ollama evicts the Qwen model whenever Gemma is loaded, which
        # defeats the warm-residency measurement for the single-Qwen route.
        routes = [
            ("before_gemma_qwen", before, True),
            ("after_qwen", after, False),
        ]
        for label, module, unload_after_extraction in routes:
            for index, case in enumerate(cases):
                memory_text = (
                    json.dumps({"id": 1, "content": case["memory"], "status": "unverified_interpretation"}, ensure_ascii=False) + "\n"
                    if case["memory"] else ""
                )
                after.MEMORY_FILE.write_text(memory_text, encoding="utf-8")
                print(f"starting {label}: {case['id']}", flush=True)
                comparisons[index][label] = run_condition(
                    label, module, after.MEMORY_FILE, case["history"], case["current"],
                    unload_on_second_call=unload_after_extraction,
                )
        results = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_count": len(comparisons),
            "cases": comparisons,
            "note": "Grouped warm-Qwen route comparison using one synthetic memory-continuity case and the existing 12-item held-out transfer set. All historical Gemma-answer/Qwen-extraction cases run first, with Qwen unloaded after extraction; only after that block completes are all Qwen-only cases run consecutively, keeping Qwen resident across them. This avoids Ollama evicting Qwen between interleaved routes. The comparison remains descriptive and requires qualitative scoring.",
        }
        path = ROOT / "migration_route_comparison_suite_v3.json"
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"Saved: {path}")
    finally:
        after.MEMORY_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
