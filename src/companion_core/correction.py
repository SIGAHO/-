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
        ("not_a_but_b", re.compile(r"(?<![^、。！？\n])(?P<old>[^、。！？\n]{1,40}?)(?:じゃなくて|ではなくて|ではなく|じゃなく)(?!て)(?P<new>[^、。！？\n]{1,60})(?![^、。！？\n])")),
        ("means", re.compile(r"(?<![^、。！？\n])(?P<old>[^、。！？\n]{1,30}?)(?:っていうのは|ってのは|というのは)(?P<new>[^、。！？\n]{1,80}?)(?:って意味|という意味|って話)(?:だよ|だね|なんだ|です|だ)?(?=$|[。！!\n])")),
        ("no_it_is", re.compile(r"(?:^|[。！？\n])\s*(?:違う|ちがう)[、,\s]+(?P<new>[^、。！？\n]{1,80})(?![^、。！？\n])")),
    ]

    # These phrases reject a previous answer without supplying a new value.
    # Meaning definitions may contain negation (e.g. 違和感がない), so do not
    # reject arbitrary negative suffixes or individual words such as 違う.
    UNRESOLVED_VALUE = re.compile(
        r"(?:(?:これ|それ|あれ|ここ|そこ|あそこ|こう|そう|ああ)"
        r"(?:(?:じゃ|では|で)ない.*)?|違う|ちがう|分からない|わからない)"
        r"(?:です|だ|んだ|よ|ね)*"
    )

    def detect(self, text: str) -> list[Correction]:
        # If one replacement exceeds the bounded parser, do not silently choose
        # a different candidate in the same utterance as the sole correction.
        if re.search(r'(?:って意味|という意味|って話)(?:ではない|じゃない|でない|ではありません|じゃありません|かもしれない|かも|ですか|なのか|[?？])', text):
            return []
        if (re.search(r'(?:じゃなくて|ではなくて|ではなく|じゃなく)[^。！？\n]*[?？]', text)
                or re.search(r'(?:^|[。！？\n])\s*(?:違う|ちがう)[、,\s]+[^。！？\n]*[?？]', text)):
            return []
        for clause in re.split(r'[、。！？!\n]', text):
            replacement = re.search(r'じゃなくて|ではなくて|ではなく|じゃなく', clause)
            if replacement and (len(clause[:replacement.start()]) > 40 or len(clause[replacement.end():]) > 60):
                return []
            definition = re.search(r'っていうのは|ってのは|というのは', clause)
            if definition:
                value = re.split(r'って意味|という意味|って話', clause[definition.end():], maxsplit=1)[0]
                if len(clause[:definition.start()]) > 30 or len(value) > 80:
                    return []
                # An incomplete or qualified definition must not disappear
                # and make a different correction look uniquely applicable.
                if not self.PATTERNS[1][1].fullmatch(clause.strip()):
                    return []
        if re.search(r'(?:^|[。！？\n])\s*(?:違う|ちがう)[、,\s]+[^、。！？\n]{81,}', text):
            return []
        found: list[tuple[int, Correction]] = []
        for name, pattern in self.PATTERNS:
            for m in pattern.finditer(text):
                gd = m.groupdict()
                old = gd.get("old")
                new = gd.get("new", "").strip()
                if re.search(r'(?:かもしれない|かも(?:ね|な)?|だろう(?:ね|な)?|だと思う)[。\s]*$', new):
                    return []
                if not new or self.UNRESOLVED_VALUE.fullmatch(new):
                    continue
                if name == "no_it_is" and re.search(r"じゃなく|ではなく|っていうのは|ってのは|というのは", new):
                    # A replacement/definition clause must pass its own parser;
                    # an incomplete clause cannot become a literal fallback value.
                    continue
                found.append((m.start(), Correction(
                    old=old.strip() if old else None,
                    new=new,
                    confidence=0.98 if old else 0.75,
                    pattern=name,
                )))
        # Preserve text order while exposing every candidate to the caller's
        # uniqueness gate, rather than hiding additional corrections.
        return [c for _, c in sorted(found, key=lambda x: x[0])]
