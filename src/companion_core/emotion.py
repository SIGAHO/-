from __future__ import annotations
from dataclasses import dataclass, asdict
import re


@dataclass
class EmotionState:
    valence: float = 0.0
    arousal: float = 0.2
    attachment: float = 0.2
    irritation: float = 0.0
    curiosity: float = 0.3
    confidence: float = 0.5

    def clipped(self):
        for k, v in asdict(self).items():
            setattr(self, k, max(-1.0 if k == "valence" else 0.0, min(1.0, v)))
        return self

    def to_dict(self):
        return asdict(self)


class EmotionEngine:
    POS = ("いい", "好き", "おもろ", "面白", "すご", "最高", "助かる", "ありがとう", "よし")
    NEG = ("嫌", "だる", "むかつ", "最悪", "無理", "クソ", "アホ", "馬鹿", "うざ")
    CURIOUS = ("なぜ", "なんで", "どうして", "？", "?", "考え", "仕組み", "構造")
    CORRECTION = ("違う", "ちがう", "じゃなく", "そうじゃ")

    def __init__(self, alpha: float = 0.72):
        self.alpha = alpha
        self.state = EmotionState()
        self.user_profile = {
            "positive_rate": 0.5,
            "correction_rate": 0.0,
            "question_rate": 0.0,
            "high_arousal_rate": 0.0,
            "n": 0,
        }

    def observe_user(self, text: str) -> EmotionState:
        pos = sum(text.count(w) for w in self.POS)
        neg = sum(text.count(w) for w in self.NEG)
        corr = int(any(w in text for w in self.CORRECTION))
        question = int(any(w in text for w in self.CURIOUS))
        exclaim = min(3, text.count("!") + text.count("！"))
        repeated = 1 if re.search(r"(.)\1{3,}", text) else 0

        impulse = EmotionState(
            valence=max(-1, min(1, 0.22*pos - 0.22*neg)),
            arousal=min(1, 0.18 + 0.16*exclaim + 0.18*repeated + 0.08*question),
            attachment=min(1, 0.22 + 0.04*pos),
            irritation=min(1, 0.20*neg + 0.14*corr),
            curiosity=min(1, 0.25 + 0.25*question),
            confidence=max(0, min(1, 0.52 - 0.10*corr)),
        )
        a = self.alpha
        for field in self.state.__dataclass_fields__:
            old = getattr(self.state, field)
            new = getattr(impulse, field)
            setattr(self.state, field, a*old + (1-a)*new)
        self.state.clipped()
        self._update_profile(pos > neg, corr, question, exclaim >= 2 or repeated)
        return self.state

    def _update_profile(self, positive: bool, correction: int, question: int, high_arousal: bool):
        self.user_profile["n"] += 1
        n = self.user_profile["n"]
        eta = min(0.25, 1 / max(2, n))
        for key, obs in [
            ("positive_rate", float(positive)),
            ("correction_rate", float(correction)),
            ("question_rate", float(question)),
            ("high_arousal_rate", float(high_arousal)),
        ]:
            self.user_profile[key] = (1-eta)*self.user_profile[key] + eta*obs
