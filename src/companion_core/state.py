from __future__ import annotations
from collections import defaultdict
import time
from .models import Fact, SourceType, Scope, Status


ALLOWED_STATE_SOURCES = {
    SourceType.RUNTIME,
    SourceType.USER_CORRECTION,
    SourceType.USER_STATEMENT,
    SourceType.VERIFIED_MEMORY,
    SourceType.SYSTEM,
}

SOURCE_PRIORITY = {
    SourceType.RUNTIME: 100,
    SourceType.USER_CORRECTION: 95,
    SourceType.USER_STATEMENT: 70,
    SourceType.VERIFIED_MEMORY: 60,
    SourceType.SYSTEM: 50,
    SourceType.ASSISTANT_GENERATED: -10_000,
}


class StateEngine:
    def __init__(self):
        self.history: dict[str, list[Fact]] = defaultdict(list)
        self.active: dict[str, Fact] = {}
        self.blocked: dict[str, set[str]] = defaultdict(set)

    @staticmethod
    def _unchanged(current: Fact | None, value, source: SourceType, scope: Scope) -> bool:
        return (current is not None and current.status == Status.ACTIVE
                and type(current.value) is type(value) and current.value == value
                and current.source == source and current.scope == scope)

    def propose(self, key: str, value, source: SourceType, scope: Scope = Scope.SESSION) -> bool:
        if source not in ALLOWED_STATE_SOURCES or (key.startswith("time.") and key != "time.user_year" and source != SourceType.RUNTIME):
            return False
        if str(value) in self.blocked[key]:
            return False
        current = self.active.get(key)
        if current and SOURCE_PRIORITY[current.source] > SOURCE_PRIORITY[source]:
            return False
        # Reobserving the same assertion is accepted without a new version.
        # Authority/scope changes remain distinct, linked history entries.
        if self._unchanged(current, value, source, scope):
            return True
        candidate = Fact(key=key, value=value, source=source, scope=scope)
        if current:
            current.status = Status.INVALIDATED
            current.superseded_by = candidate.id
            current.updated_at = time.time()
        self.history[key].append(candidate)
        self.active[key] = candidate
        return True

    def correct(self, key: str, new_value, old_value=None, scope: Scope = Scope.SESSION, *, source=SourceType.USER_CORRECTION, now=None, event_id=None) -> Fact:
        if source != SourceType.USER_CORRECTION or (key.startswith("time.") and key != "time.user_year"):
            raise ValueError("correction source or runtime key rejected")
        current = self.active.get(key)
        if old_value is None and current is not None:
            old_value = current.value
        if old_value is not None and str(old_value) != str(new_value):
            self.blocked[key].add(str(old_value))
        if self._unchanged(current, new_value, SourceType.USER_CORRECTION, scope):
            return current
        stamp = time.time() if now is None else now
        fact = Fact(
            created_at=stamp, updated_at=stamp,
            **({"id": event_id} if event_id else {}),
            key=key,
            value=new_value,
            source=SourceType.USER_CORRECTION,
            scope=scope,
        )
        if current:
            current.status = Status.INVALIDATED
            current.superseded_by = fact.id
            current.updated_at = stamp
        self.history[key].append(fact)
        self.active[key] = fact
        return fact

    def snapshot(self) -> dict:
        return {
            k: v.to_dict()
            for k, v in self.active.items()
            if v.status == Status.ACTIVE
        }
