from __future__ import annotations
import time
from .models import Topic
from .textmath import char_ngrams, jaccard_sets


class TopicTracker:
    def __init__(self, decay: float = 0.82, new_topic_threshold: float = 0.18):
        self.decay = decay
        self.new_topic_threshold = new_topic_threshold
        self.topics: list[Topic] = []

    def update(self, text: str) -> Topic | None:
        sig = set(char_ngrams(text, 2))
        if not sig:
            return self.current()
        for t in self.topics:
            t.score *= self.decay
        best = None
        best_sim = 0.0
        for t in self.topics:
            sim = jaccard_sets(sig, t.signature)
            if sim > best_sim:
                best, best_sim = t, sim
        if best is None or best_sim < self.new_topic_threshold:
            topic = Topic(label=text[:32], signature=sig, score=1.0)
            self.topics.append(topic)
            return topic
        best.signature |= sig
        best.score += 1.0 + best_sim
        best.last_seen = time.time()
        return best

    def current(self) -> Topic | None:
        if not self.topics:
            return None
        return max(self.topics, key=lambda t: t.score)

    def ranked(self, n: int = 5) -> list[Topic]:
        return sorted(self.topics, key=lambda t: t.score, reverse=True)[:n]
