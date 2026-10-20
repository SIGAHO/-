from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class Correction:
    old: str | None
    new: str
    confidence: float
    pattern: str


class CorrectionEngine:
    """Explicit correction detector only. Ambiguous cases are intentionally ignored."""

    PATTERNS = [
        ("not_a_but_b", re.compile(r"(?P<old>[^、。！？]{1,40}?)(?:じゃなくて|ではなくて|ではなく|じゃなく)(?P<new>[^、。！？]{1,60})")),
        ("means", re.compile(r"(?P<old>[^、。！？]{1,30}?)(?:っていうのは|ってのは|というのは)(?P<new>[^、。！？]{1,80}?)(?:って意味|という意味|って話)")),
        ("no_it_is", re.compile(r"(?:違う|ちがう)[、,\s]*(?P<new>[^、。！？]{1,80})")),
    ]

    def detect(self, text: str) -> list[Correction]:
        out: list[Correction] = []
        for name, pattern in self.PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            gd = m.groupdict()
            old = gd.get("old")
            new = gd.get("new", "").strip()
            if not new:
                continue
            out.append(Correction(
                old=old.strip() if old else None,
                new=new,
                confidence=0.98 if old else 0.75,
                pattern=name,
            ))
        return out
