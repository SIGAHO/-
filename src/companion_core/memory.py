from __future__ import annotations
import math
import time
from .models import MemoryItem, SourceType, Status
from .textmath import cosine_text


ALLOWED_MEMORY_SOURCES = {
    SourceType.RUNTIME,
    SourceType.USER_CORRECTION,
    SourceType.USER_STATEMENT,
    SourceType.VERIFIED_MEMORY,
    SourceType.SYSTEM,
}


class MemoryEngine:
    def __init__(self):
        self.items: list[MemoryItem] = []

    def add(self, text: str, source: SourceType, importance: float = 0.5, *, now: float | None = None) -> bool:
        if source not in ALLOWED_MEMORY_SOURCES:
            return False
        if not text.strip():
            return False
        for x in self.items:
            # A one-character change in a correction can change its fact value
            # (time.user_year = 2023 vs 2026). Never merge these approximately
            # or collapse their source into an ordinary user statement.
            protected = source == SourceType.USER_CORRECTION or x.source == SourceType.USER_CORRECTION
            duplicate = source == x.source and ((text.strip() == x.text) if protected else cosine_text(text, x.text) > 0.92)
            if x.status == Status.ACTIVE and duplicate:
                x.mentions += 1
                x.importance = min(1.0, max(x.importance, importance))
                return True
        self.items.append(MemoryItem(
            text=text.strip(),
            source=source,
            importance=max(0.0, min(1.0, importance)),
            created_at=time.time() if now is None else now,
            last_used_at=time.time() if now is None else now,
        ))
        return True

    def reliable_context(self, query: str, *, subjects=()) -> list[str]:
        """Only explicitly trusted evidence, never user mentions or AI output.

        Reliability is separate from retrieval's recency/importance ranking.
        All query content terms and requested facets must be covered.
        """
        from .knowledge import entities, supports
        subjects = subjects or tuple(entities(query))
        trusted = {SourceType.VERIFIED_MEMORY, SourceType.RUNTIME, SourceType.SYSTEM}
        return [x.text for x in self.items if x.status == Status.ACTIVE
                and x.source in trusted and supports(query, x.text, subjects)]

    def has_reliable_context(self, query: str) -> bool:
        return bool(self.reliable_context(query))

    def archive_old(self, now: float | None = None, tau_days: float = 60.0, epsilon: float = 0.08) -> None:
        now = now or time.time()
        tau = tau_days * 86400
        for x in self.items:
            if x.status != Status.ACTIVE:
                continue
            age = max(0.0, now - x.created_at)
            strength = x.importance * math.exp(-age / tau) * (1 + 0.15 * math.log1p(x.mentions))
            if strength < epsilon:
                x.status = Status.ARCHIVED

    def retrieve(self, query: str, budget_chars: int = 1200, limit: int = 8) -> list[MemoryItem]:
        if not query.strip() or limit <= 0 or budget_chars <= 0:
            return []
        now = time.time()
        scored = []
        for x in self.items:
            if x.status != Status.ACTIVE:
                continue
            rel = cosine_text(query, x.text)
            age_days = max(0.0, now - x.created_at) / 86400
            recency = math.exp(-age_days / 30.0)
            reuse = min(1.0, math.log1p(x.mentions) / 3.0)
            score = 0.58*rel + 0.17*recency + 0.18*x.importance + 0.07*reuse
            scored.append([score, x])
        scored.sort(key=lambda z: z[0], reverse=True)

        selected: list[MemoryItem] = []
        used = 0
        for base_score, item in scored:
            redundancy = max((cosine_text(item.text, y.text) for y in selected), default=0.0)
            adjusted = base_score - 0.28 * redundancy
            if adjusted <= 0.08:
                continue
            cost = len(item.text)
            if used + cost > budget_chars:
                continue
            selected.append(item)
            item.last_used_at = now
            used += cost
            if len(selected) >= limit:
                break
        return selected
