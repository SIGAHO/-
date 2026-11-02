"""Push-event compression for Breaktail's process-local nervous system.

Raw observations never become facts merely by arriving here.  The store keeps
their source/provenance, exposes a small current state, and only promotes
important changes into ``recent_events`` for the language model.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from breaktail_bus import Observation


PUSH_CAPABILITIES = frozenset({
    "system.time", "system.idle", "system.active_window", "screen.changed",
    "notification.arrived", "file.modified", "task.result", "capability.changed",
    "memory.candidate",
})


@dataclass(frozen=True)
class FilterDecision:
    importance: int
    deliver: bool
    reason: str


class ChangeDetector:
    """Drops repeated observations with the same meaningful payload."""

    def __init__(self) -> None:
        self._last: dict[str, dict[str, Any]] = {}

    def changed(self, observation: Observation) -> bool:
        previous = self._last.get(observation.capability)
        current = dict(observation.payload)
        self._last[observation.capability] = current
        return previous != current


class ImportanceFilter:
    """Conservative routing; DND suppresses only non-urgent observations."""

    URGENT = {"task.result", "capability.changed"}
    IMPORTANT = {"notification.arrived", "file.modified", "memory.candidate"}

    def decide(self, observation: Observation, *, changed: bool, dnd: bool) -> FilterDecision:
        if not changed:
            return FilterDecision(0, False, "unchanged")
        payload = observation.payload
        if observation.capability == "screen.changed" and not payload.get("summary"):
            return FilterDecision(0, False, "no_lightweight_summary")
        if observation.capability in self.URGENT or payload.get("urgent") is True:
            return FilterDecision(3, True, "urgent")
        if observation.capability in self.IMPORTANT:
            if dnd:
                return FilterDecision(2, False, "dnd_suppressed")
            return FilterDecision(2, True, "important_change")
        if observation.capability in {"system.time", "system.idle", "system.active_window", "screen.changed"}:
            return FilterDecision(1, not dnd and observation.capability == "system.active_window", "ambient_state")
        return FilterDecision(1, False, "unclassified_push")


class StateStore:
    """A bounded projection of push observations, not an event log or memory."""

    def __init__(self, *, recent_limit: int = 8) -> None:
        self.change_detector = ChangeDetector()
        self.filter = ImportanceFilter()
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._state: dict[str, Any] = {
            "time": None, "idle_sec": None, "active_app": None, "screen_summary": None,
            "recent_events": [], "attention": None, "current_task": None,
            "pending_event": None, "memory_candidates": [], "capability_status": {},
            "do_not_disturb": False,
        }

    def set_attention(self, attention: str | None, *, current_task: str | None = None, do_not_disturb: bool = False) -> None:
        self._state["attention"] = attention
        self._state["current_task"] = current_task
        self._state["do_not_disturb"] = bool(do_not_disturb)

    def ingest(self, observation: Observation) -> FilterDecision:
        if observation.capability not in PUSH_CAPABILITIES:
            return FilterDecision(0, False, "unsupported_push_capability")
        changed = self.change_detector.changed(observation)
        decision = self.filter.decide(observation, changed=changed, dnd=self._state["do_not_disturb"])
        payload = observation.payload
        if observation.capability == "system.time":
            self._state["time"] = payload.get("local_time")
        elif observation.capability == "system.idle":
            self._state["idle_sec"] = payload.get("idle_sec")
        elif observation.capability == "system.active_window":
            self._state["active_app"] = payload.get("app")
        elif observation.capability == "screen.changed":
            self._state["screen_summary"] = payload.get("summary")
        elif observation.capability == "memory.candidate" and payload.get("candidate"):
            candidates = self._state["memory_candidates"]
            candidates.append({"candidate": payload["candidate"], "confidence": observation.confidence,
                               "provenance": observation.provenance, "trace_id": observation.trace_id})
            del candidates[:-3]
        elif observation.capability == "capability.changed":
            name, status = payload.get("name"), payload.get("status")
            if name and status:
                self._state["capability_status"][name] = status
        if decision.deliver:
            event = {"capability": observation.capability, "summary": payload.get("summary") or payload.get("message") or payload,
                     "importance": decision.importance, "timestamp": observation.timestamp, "trace_id": observation.trace_id,
                     "provenance": observation.provenance}
            self._recent.append(event)
            self._state["pending_event"] = event
        self._state["recent_events"] = list(self._recent)
        return decision

    def snapshot(self) -> dict[str, Any]:
        """Return a copy so callers cannot mutate current state."""
        import copy
        state = copy.deepcopy(self._state)
        state["capability_status"] = dict(sorted(state["capability_status"].items()))
        return state
