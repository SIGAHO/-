from __future__ import annotations
import math
import re
from collections import Counter


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def char_ngrams(text: str, n: int = 2) -> list[str]:
    s = re.sub(r"\s+", "", normalize_text(text))
    if len(s) < n:
        return [s] if s else []
    return [s[i:i+n] for i in range(len(s) - n + 1)]


def cosine_text(a: str, b: str) -> float:
    ca, cb = Counter(char_ngrams(a)), Counter(char_ngrams(b))
    if not ca or not cb:
        return 0.0
    dot = sum(ca[k] * cb.get(k, 0) for k in ca)
    na = math.sqrt(sum(v*v for v in ca.values()))
    nb = math.sqrt(sum(v*v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


def jaccard_sets(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
