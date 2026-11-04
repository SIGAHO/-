"""Phase 7.14: small, deterministic continuity state; never sends a message."""

from __future__ import annotations

import re
from datetime import datetime

from breaktail_runtime_facts import collect_clock

SCHEMA_VERSION = 1
MAX_OPEN_LOOPS = 4
MAX_RECENT_EVENTS = 4
CONTINUITY_THRESHOLD_SECONDS = 3 * 60 * 60


def _now(now: datetime | None = None) -> datetime:
    """Use the existing RuntimeFacts OS clock rather than a second clock."""
    if now is not None:
        return now
    clock = next(item for item in collect_clock() if item.key == "clock.current_datetime_iso")
    return datetime.fromisoformat(str(clock.value))


def new_passive_continuity_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "last_seen_at": None, "open_loops": [],
            "recent_events": [], "attention_target": None, "initiative_pressure": 0.0}


def normalize_passive_continuity_state(value: dict | None) -> dict:
    state = new_passive_continuity_state()
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return state
    state["last_seen_at"] = value.get("last_seen_at") if isinstance(value.get("last_seen_at"), str) else None
    state["open_loops"] = [item for item in value.get("open_loops", []) if isinstance(item, dict)
                           and isinstance(item.get("summary"), str)][-MAX_OPEN_LOOPS:]
    state["recent_events"] = [item for item in value.get("recent_events", []) if isinstance(item, dict)
                              and isinstance(item.get("type"), str) and isinstance(item.get("summary"), str)
                              and isinstance(item.get("at"), str)][-MAX_RECENT_EVENTS:]
    state["attention_target"] = value.get("attention_target") if isinstance(value.get("attention_target"), str) else None
    try:
        state["initiative_pressure"] = max(0.0, min(1.0, float(value.get("initiative_pressure", 0.0))))
    except (TypeError, ValueError):
        pass
    return state


def elapsed_seconds(state: dict, now: datetime | None = None) -> int:
    stamp = state.get("last_seen_at")
    if not stamp:
        return 0
    try:
        return max(0, int((_now(now) - datetime.fromisoformat(stamp)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def _event(state: dict, event_type: str, summary: str, now: datetime) -> None:
    state["recent_events"] = (state["recent_events"] + [{"type": event_type, "summary": summary, "at": now.isoformat()}])[-MAX_RECENT_EVENTS:]


def _explicit_loop(user_text: str) -> str | None:
    text = re.sub(r"\s+", " ", user_text or "").strip()
    match = re.search(r"(.{0,40}(?:帰ったら|あとで|次に).{1,45}(?:話そう|続き(?:を)?(?:やろう|する)|やろう|する))", text)
    return match.group(1).strip("。 、") if match else None


def _pressure(state: dict, elapsed: int) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if state["open_loops"] and elapsed >= 6 * 3600:
        score += 0.45; reasons.append("open_loop_unresolved_6h")
    if any("帰ったら" in item.get("summary", "") for item in state["recent_events"]) and elapsed >= 2 * 3600:
        score += 0.30; reasons.append("return_expected_2h")
    if elapsed < 30 * 60:
        score -= 0.20; reasons.append("recent_user_activity_decay")
    return max(0.0, min(1.0, round(score, 2))), reasons


def prepare_user_turn(state: dict | None, user_text: str, working_pending: list | None = None,
                      now: datetime | None = None) -> tuple[dict, str, dict]:
    """Build optional pre-update context, then record this user utterance.

    ``working_pending`` is read only: Working State remains the single source of
    truth for pending data.
    """
    state = normalize_passive_continuity_state(state)
    current = _now(now)
    elapsed = elapsed_seconds(state, current)
    prior_loops = list(state["open_loops"])
    lines = []
    if state["last_seen_at"] and elapsed >= CONTINUITY_THRESHOLD_SECONDS:
        hours = elapsed // 3600
        lines.append(f"前回の会話から約{hours}時間経過")
        if prior_loops:
            lines.append("未完了: " + prior_loops[-1]["summary"][:80])
        elif state.get("attention_target"):
            lines.append("直近の注目対象: " + state["attention_target"][:80])
    section = "[Continuity: 時間経過した会話状態。必要な場合だけ自然に参照し、事実以上に推測しない]\n" + "\n".join("- " + line for line in lines) if lines else ""
    loop = _explicit_loop(user_text)
    if loop:
        state["open_loops"] = ([item for item in state["open_loops"] if item.get("summary") != loop] + [{"summary": loop, "at": current.isoformat()}])[-MAX_OPEN_LOOPS:]
        _event(state, "open_loop", loop, current)
    # Do not copy pending; expose it only via read-only trace metadata.
    target = state["open_loops"][-1]["summary"] if state["open_loops"] else None
    state["attention_target"] = target
    state["last_seen_at"] = current.isoformat()
    pressure, reasons = _pressure(state, elapsed)
    state["initiative_pressure"] = pressure
    meta = {"last_seen_at": state["last_seen_at"], "elapsed_seconds": elapsed,
            "open_loop_count": len(state["open_loops"]), "attention_target": state["attention_target"],
            "initiative_pressure": pressure, "pressure_reasons": reasons,
            "continuity_section_chars": len(section), "pending_mirror_count": len(working_pending or [])}
    return state, section, meta
