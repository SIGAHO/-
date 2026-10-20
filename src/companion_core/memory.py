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

    def add(self, text: str, source: SourceType, importance: float = 0.5) -> bool:
        if source not in ALLOWED_MEMORY_SOURCES:
            return False
        if not text.strip():
            return False
        for x in self.items:
            if x.status == Status.ACTIVE and cosine_text(text, x.text) > 0.92:
                x.mentions += 1
                x.importance = min(1.0, max(x.importance, importance))
                return True
        self.items.append(MemoryItem(
            text=text.strip(),
            source=source,
            importance=max(0.0, min(1.0, importance)),
        ))
        return True

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
