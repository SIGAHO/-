"""Domain-independent discourse evidence from a fixed morphological analyzer."""
from dataclasses import dataclass
from functools import lru_cache
from janome.tokenizer import Tokenizer


@lru_cache(maxsize=1)
def _tokenizer():
    return Tokenizer()


@dataclass(frozen=True)
class Evidence:
    heads: frozenset[str]
    terms: frozenset[str]
    objects: frozenset[str]
    predicate: str | None
    nominal: bool
    dependent: bool
    contrast: bool
    request: bool
    progressive: bool


@lru_cache(maxsize=2048)
def analyze(text: str) -> Evidence:
    tokens = list(_tokenizer().tokenize(text))
    heads, terms, objects = set(), set(), set()
    phrase = set()
    predicates = []
    pronoun = False
    question = "?" in text or "？" in text
    contrast = False
    predicative = False
    request = False
    progressive = False
    previous = None
    for token in tokens:
        pos = token.part_of_speech.split(",")
        base = token.base_form if token.base_form != "*" else token.surface
        progressive |= bool(previous and previous.surface in {"て", "で"}
                            and pos[0] == "動詞" and pos[1] == "非自立" and base in {"いる", "おる"})
        # Grammatical request/wish auxiliaries, independent of domain nouns.
        request |= (pos[0] == "助動詞" and base == "たい") or (pos[0] == "動詞" and pos[1] == "非自立" and base in {"くださる", "いただく"})
        noun = pos[0] == "名詞" and pos[1] not in {"非自立", "代名詞", "数", "接尾", "副詞可能", "サ変接続", "形容動詞語幹"}
        if noun:
            heads.add(base)
            terms.add(base)
            phrase.add(base)
        elif pos[0] == "名詞":
            pronoun |= pos[1] == "代名詞"
        if pos[0] == "動詞" and pos[1] == "自立":
            predicative = True
            predicate = base
            if base == "する" and previous and previous.part_of_speech.startswith("名詞,サ変接続"):
                predicate = previous.base_form + base
            predicates.append(predicate)
        elif pos[0] == "形容詞" or (pos[0] == "名詞" and pos[1] == "形容動詞語幹"):
            predicative = True
            predicates.append(base)
        elif pos[0] == "助動詞":
            predicative = True
        if pos[0] == "助詞":
            if token.surface in {"を", "は", "が", "も"}:
                objects.update(phrase)
            question |= token.surface == "か" and pos[1] in {"終助詞", "副助詞／並立助詞／終助詞"}
            phrase.clear()
        elif pos[0] == "接続詞":
            contrast = True
            phrase.clear()
        elif pos[0] not in {"名詞", "接頭詞", "記号"}:
            phrase.clear()
        previous = token
    return Evidence(frozenset(heads), frozenset(terms), frozenset(objects),
                    predicates[-1] if predicates else None,
                    bool(heads) and not predicative and not question,
                    pronoun or question or not heads, contrast, request or question, progressive)
