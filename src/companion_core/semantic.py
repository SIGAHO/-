from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .textmath import cosine_text


def cosine_vector(a: list[float], b: list[float]) -> float:
    """Return cosine similarity; reject missing and malformed embeddings."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


class LocalOllamaEmbeddings:
    """Semantic vectorization using Ollama only on 127.0.0.1."""
    ENDPOINT = "http://127.0.0.1:11434/api/embed"

    def __init__(self, model: str = "bge-m3", timeout: int = 90):
        self.model = model
        self.timeout = timeout
        self.cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        if text in self.cache:
            return self.cache[text]
        req = Request(
            self.ENDPOINT,
            data=json.dumps({"model": self.model, "input": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as response:
                data = json.load(response)
            vector = data["embeddings"][0]
            if not isinstance(vector, list) or not vector or not all(
                isinstance(x, (float, int)) and math.isfinite(x) for x in vector
            ):
                raise ValueError("Malformed embedding")
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"ローカル埋め込みモデル {self.model} を確認してください: "
                f"ollama pull {self.model}"
            ) from exc
        result = [float(v) for v in vector]
        self.cache[text] = result
        return result


class SemanticMemoryRetriever:
    """Local embedding-based recall; does not alter trusted fact admission."""

    def __init__(self, embedder: LocalOllamaEmbeddings, minimum_similarity: float = 0.30):
        self.embedder = embedder
        self.minimum_similarity = minimum_similarity

    def retrieve(self, query: str, items: list, limit: int = 8, budget_chars: int = 1200):
        active = [m for m in items if m.status.value == "active"]
        if not active:
            return []
        vectors = [query] + [m.text for m in active]
        scored = []
        query_vec = self.embedder.embed(vectors[0])
        for item in active:
            semantic = cosine_vector(query_vec, self.embedder.embed(item.text))
            if semantic < self.minimum_similarity:
                continue
            lexical = cosine_text(query, item.text)
            score = 0.85 * semantic + 0.15 * lexical
            scored.append((score, item.created_at, item.id, item))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        selected = []
        used = 0
        for score, _, _, item in scored:
            if used + len(item.text) > budget_chars:
                continue
            selected.append({"id": item.id, "text": item.text, "score": round(score, 4)})
            used += len(item.text)
            if len(selected) == limit:
                break
        return selected
