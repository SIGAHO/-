"""The single prompt gateway for SelfRuntime, RuntimeFacts and operation results."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from breaktail_fact_resolver import resolve_fact_groups
from breaktail_runtime_facts import (
    RUNTIME_FACTS, FactStore, RuntimeFact, collect_capabilities, collect_clock,
    collect_context_state, collect_last_error, collect_local_service, collect_system_identity, collect_system_disk, collect_system_cpu,
    collect_memory_state, collect_system_memory, fact, ollama_endpoint,
)


def deterministic_evaluate(text: str, now: datetime) -> dict | None:
    """Evaluate only narrow, explicit arithmetic/comparison/unit/date patterns."""
    normalized = text.strip().replace("，", ",").replace("＋", "+").replace("－", "-")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(秒|分|時間|日)?\s*と\s*(-?\d+(?:\.\d+)?)\s*\2?\s*の差", normalized)
    if match:
        left, right = float(match.group(1)), float(match.group(3))
        result = abs(left - right)
        unit = match.group(2) or ""
        shown = int(result) if result.is_integer() else result
        return {"kind": "difference", "operands": [left, right], "unit": unit,
                "result": shown, "answer_core": f"差は{shown}{unit}。"}

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*と\s*(-?\d+(?:\.\d+)?)\s*(?:は)?\s*(?:どっち|どちら).{0,6}(大き|小さ)", normalized)
    if match:
        left, right, direction = float(match.group(1)), float(match.group(2)), match.group(3)
        if left == right:
            answer, result = "同じ。", left
        else:
            result = max(left, right) if direction == "大き" else min(left, right)
            shown = int(result) if result.is_integer() else result
            answer = f"{shown}。"
        return {"kind": "comparison", "operands": [left, right], "comparison": direction,
                "result": result, "answer_core": answer}

    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([+\-*/×÷])\s*(-?\d+(?:\.\d+)?)\s*[=＝]?\s*[？?]?\s*", normalized)
    if match:
        left, op, right = float(match.group(1)), match.group(2), float(match.group(3))
        if op in {"/", "÷"} and right == 0:
            return {"kind": "arithmetic", "status": "failed", "answer_core": "0では割れない。"}
        result = {"+": left + right, "-": left - right, "*": left * right,
                  "×": left * right, "/": left / right, "÷": left / right}[op]
        shown = int(result) if result.is_integer() else round(result, 10)
        return {"kind": "arithmetic", "operands": [left, right], "operator": op,
                "result": shown, "answer_core": f"答えは{shown}。"}

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(秒|分|時間|日)\s*(?:は|を|って)\s*(?:何)?(秒|分|時間|日)(?:にすると|へ変換|で)?", normalized)
    if match:
        value, source, target = float(match.group(1)), match.group(2), match.group(3)
        seconds = value * {"秒": 1, "分": 60, "時間": 3600, "日": 86400}[source]
        result = seconds / {"秒": 1, "分": 60, "時間": 3600, "日": 86400}[target]
        shown = int(result) if result.is_integer() else round(result, 10)
        return {"kind": "unit_conversion", "input": value, "from": source, "to": target,
                "result": shown, "answer_core": f"{shown}{target}。"}

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:の|のうち)?\s*(-?\d+(?:\.\d+)?)\s*%", normalized)
    if match:
        value, percent = float(match.group(1)), float(match.group(2))
        result = value * percent / 100
        shown = int(result) if result.is_integer() else round(result, 10)
        return {"kind": "percentage", "input": value, "percent": percent, "result": shown,
                "answer_core": f"{shown}。"}

    if re.search(r"(?:明日まで|今日から明日).{0,8}(?:何日|日数|差)", normalized):
        return {"kind": "date_difference", "from": now.date().isoformat(),
                "to": (now.date() + timedelta(days=1)).isoformat(), "days": 1,
                "answer_core": "1日。"}
    if re.search(r"(?:昨日から今日|今日と昨日).{0,8}(?:何日|日数|差)", normalized):
        return {"kind": "date_difference", "from": (now.date() - timedelta(days=1)).isoformat(),
                "to": now.date().isoformat(), "days": 1, "answer_core": "1日。"}
    if re.search(r"明日.{0,5}(?:何月何日|何日|日付)", normalized):
        target = now.date() + timedelta(days=1)
        return {"kind": "relative_date", "relative": "tomorrow", "date": target.isoformat(),
                "answer_core": f"明日は{target.year}年{target.month}月{target.day}日。"}
    if re.search(r"昨日.{0,5}(?:何月何日|何日|日付)", normalized):
        target = now.date() - timedelta(days=1)
        return {"kind": "relative_date", "relative": "yesterday", "date": target.isoformat(),
                "answer_core": f"昨日は{target.year}年{target.month}月{target.day}日。"}
    if re.search(r"来年.{0,4}(?:何年|年)", normalized):
        return {"kind": "relative_year", "relative": "next_year", "year": now.year + 1,
                "answer_core": f"来年は{now.year + 1}年。"}
    if re.search(r"去年.{0,4}(?:何年|年)", normalized):
        return {"kind": "relative_year", "relative": "last_year", "year": now.year - 1,
                "answer_core": f"去年は{now.year - 1}年。"}
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*まで.{0,8}(?:あと何日|何日|期限差)", normalized)
    if match:
        try:
            target = date.fromisoformat(match.group(1))
        except ValueError:
            return None
        days = (target - now.date()).days
        return {"kind": "deadline_difference", "from": now.date().isoformat(),
                "to": target.isoformat(), "days": days,
                "answer_core": f"あと{days}日。" if days >= 0 else f"期限から{-days}日経過。"}
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:から|と)\s*(\d{4}-\d{2}-\d{2}).{0,8}(?:何日|日数|差)", normalized)
    if match:
        try:
            first, second = date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))
        except ValueError:
            return None
        days = abs((second - first).days)
        return {"kind": "date_difference", "from": first.isoformat(), "to": second.isoformat(),
                "days": days, "answer_core": f"{days}日。"}
    return None


def _put_many(store: FactStore, facts: list[RuntimeFact]) -> None:
    for item in facts:
        store.put(item)


def build_runtime_context(user_text: str, capabilities: dict, *, history_count: int = 0,
                          max_history_messages: int = 32, num_ctx: int = 8192,
                          trim_occurred: bool = False, memory_file: Path | None = None,
                          ollama_url: str = "http://127.0.0.1:11434/api/chat",
                          web_host: str = "127.0.0.1", web_port: int = 8765,
                          error_sources: dict[str, object] | None = None,
                          store: FactStore = RUNTIME_FACTS,
                          now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    selected = resolve_fact_groups(user_text)
    _put_many(store, collect_clock(now))
    store.put(collect_capabilities(capabilities, now))
    _put_many(store, store.operation_facts(now))

    if "system.memory" in selected:
        store.put(collect_system_memory(now))
    if "system.identity" in selected:
        store.put(collect_system_identity(now))
    if "system.disk" in selected:
        store.put(collect_system_disk(now))
    if "system.cpu" in selected:
        store.put(collect_system_cpu(now))
    if "memory.state" in selected:
        store.put(collect_memory_state(memory_file or Path("__memory_not_configured__"), now))
    if "context.state" in selected:
        store.put(collect_context_state(history_count, max_history_messages, num_ctx, trim_occurred, now))
    if "last_error" in selected:
        store.put(collect_last_error(error_sources, now))
    if "service.ollama" in selected:
        endpoint = ollama_endpoint(ollama_url)
        store.put(collect_local_service("service.ollama", *endpoint, now=now) if endpoint else
                  fact("service.ollama", None, "local_tcp_probe", status="unknown", ttl_seconds=2,
                       observed_at=now.isoformat()))
    if "service.web" in selected:
        store.put(collect_local_service("service.web", web_host, web_port, now=now))
    if "network.local" in selected:
        store.put(fact("network.local", {"scope": "loopback_only", "external_access_attempted": False},
                       "runtime_network_policy", observed_at=now.isoformat()))

    keys = {"capabilities", "operation.current", "operation.last_result"}
    keys.update(f"clock.{name}" for name in ("current_datetime_iso", "current_date", "current_year", "current_time", "timezone"))
    keys.update(selected - {"clock", "capabilities", "operation"})
    deterministic = deterministic_evaluate(user_text, now)
    if deterministic:
        store.put(fact("deterministic.result", deterministic, "deterministic_runtime_evaluator",
                       status=deterministic.get("status", "ok"), observed_at=now.isoformat()))
        keys.add("deterministic.result")
    facts = store.snapshot(keys, now)
    prompt = "[Runtime Context]\n"
    prompt += "以下はコードが現在観測・計算した事実。選択されたFactだけを含む。推測で欠損を補完しない。\n"
    prompt += "statusがstale/failed/not_connected/unknownなら、valueを成功・0・falseとして扱わない。操作はsuccessful=trueの時だけ成功済みと言う。\n"
    prompt += json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    return {"version": 1, "selected_groups": sorted(selected), "facts": facts,
            "deterministic": deterministic, "prompt": prompt}

