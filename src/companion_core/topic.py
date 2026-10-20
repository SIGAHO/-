from __future__ import annotations
import re
import time
from .models import Topic
from .textmath import normalize_text, jaccard_sets


class TopicTracker:
    # A small, explicit noun lexicon; not a claim of general semantic parsing.
    # Callers can add domain vocabulary without special-casing whole utterances.
    DEFAULT_ALIASES = {
        "基板": ("プリント配線板", "プリント基板", "pcb"),
        "時計": ("腕時計", "ウォッチ"),
        "寿司": ("すし", "スシ"),
    }
    GENERIC_PHRASES = (
        "切削加工する", "加工する", "切削する", "製作する", "制作する",
        "調べる", "確認する", "考える", "知りたい", "について", "に関して",
        "作りたい", "作る", "削る", "買う", "仕組み", "続き",
    )
    GENERIC_WORDS = {
        "を", "が", "は", "の", "に", "で", "と", "も", "する", "した", "して",
        "です", "ます", "だ", "たい", "話", "話題", "こと", "もの", "仕組み",
        "構造", "方法", "作業", "加工", "切削", "製作", "制作", "続き",
    }

    def __init__(self, decay: float = 0.82, new_topic_threshold: float = 0.18,
                 *, aliases: dict[str, tuple[str, ...]] | None = None):
        self.decay = decay
        self.new_topic_threshold = new_topic_threshold
        self.topics: list[Topic] = []
        self._current: Topic | None = None
        self._aliases: dict[str, str] = {}
        self._subjects: set[str] = set()
        for canonical, variants in {**self.DEFAULT_ALIASES, **(aliases or {})}.items():
            canonical = normalize_text(canonical)
            if not canonical:
                raise ValueError("Topic aliases require a nonempty canonical noun")
            self._subjects.add(canonical)
            for term in (canonical, *variants):
                term = normalize_text(term)
                if not term or (term in self._aliases and self._aliases[term] != canonical):
                    raise ValueError("Topic aliases must be nonempty and unambiguous")
                self._aliases[term] = canonical
        # ASCII aliases must not match substrings inside other identifiers.
        alternatives = [rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])"
                        if re.fullmatch(r"[a-z0-9_]+", term) else re.escape(term)
                        for term in sorted(self._aliases, key=lambda x: (-len(x), x))]
        self._alias_pattern = re.compile("|".join(alternatives))
        self._generic_pattern = re.compile("|".join(map(re.escape, self.GENERIC_PHRASES)))

    def _signature(self, text: str) -> set[str]:
        normalized = self._alias_pattern.sub(lambda m: " " + self._aliases[m[0]] + " ", normalize_text(text))
        normalized = self._generic_pattern.sub(" ", normalized)
        words = re.findall(r"[一-龯々]+|[ァ-ヺー]+|[a-z0-9_]+|[ぁ-ゖ]+", normalized)
        return set(words) - self.GENERIC_WORDS

    def update(self, text: str) -> Topic | None:
        sig = self._signature(text)
        if not sig:
            return self.current()
        for t in self.topics:
            t.score *= self.decay
        best = None
        best_sim = 0.0
        subjects = sig & self._subjects
        for t in self.topics:
            previous_subjects = t.signature & self._subjects
            if subjects and previous_subjects:
                # A shared tool/verb cannot override different named objects.
                # Comparisons of several objects have their own subject set,
                # preventing bridge turns from polluting either single topic.
                if subjects != previous_subjects:
                    continue
                sim = 1.0
            else:
                sim = jaccard_sets(sig, t.signature)
            if sim > best_sim:
                best, best_sim = t, sim
        if best is None or best_sim < self.new_topic_threshold:
            topic = Topic(label=text[:32], signature=sig, score=1.0)
            self.topics.append(topic)
            self._current = topic
            return topic
        best.signature |= sig
        best.score += 1.0 + best_sim
        best.last_seen = time.time()
        self._current = best
        return best

    def current(self) -> Topic | None:
        return self._current

    def ranked(self, n: int = 5) -> list[Topic]:
        return sorted(self.topics, key=lambda t: t.score, reverse=True)[:n]
