"""Conservative CPU evidence gate; the model never decides whether to search."""
from dataclasses import asdict, dataclass
import re
import unicodedata
from .models import SourceType, Status
from .topic_evidence import _tokenizer


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


FACT_REQUEST = re.compile(r"[?？]|知って|教えて|説明|解説|調べ|紹介|誰|だれ|何者|いつ|どこ|どんな|について|とは|って何|歌手|作者|発売|値段|価格|最新")
REFERENTIAL = re.compile(r"その|それ|さっきの|あの|続き")
EXPLICIT_REQUEST = re.compile(r"[?？]|教えて|説明|解説|誰|だれ|どんな|知って|調べ|いつ|いくら")
UNCERTAIN = re.compile(r"[?？]|知って|教えて|不明|未確認|未検証|不確か|推測|かもしれ|たぶん|多分|らしい|知らない|分から|わから|ではない|じゃない")
GENERIC = {"こと", "もの", "何", "誰", "だれ", "どこ", "いつ", "曲", "作品", "人", "商品", "名前", "説明", "詳細", "情報"}
FACETS = {
    "creator": (r"誰|だれ|歌手|歌って|歌唱|作者|作曲|作詞", ("歌唱", "歌手", "歌う", "作者", "作曲", "作詞")),
    "date": (r"いつ|発売|リリース", ("発売", "リリース", "公開", "年", "月")),
    "price": (r"価格|値段|いくら", ("価格", "値段", "円", "ドル")),
    "meaning": (r"意味|テーマ|内容", ("意味", "テーマ", "内容")),
}


def entities(text):
    explicit = re.findall(r"[「『\"]([^」』\"]+)[」』\"]", text)
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_.:+-]*(?:[ \t]+[A-Za-z0-9][A-Za-z0-9_.:+-]*)*", text)
    katakana = [span for span in re.findall(r"[ァ-ヶー]{3,}", text)
                if any(t.reading == "*" or t.part_of_speech.startswith("名詞,固有名詞")
                       for t in _tokenizer().tokenize(span))]
    proper = [t.surface for t in _tokenizer().tokenize(text) if t.part_of_speech.startswith("名詞,固有名詞")]
    # Unknown Japanese titles need not appear in the dictionary as proper nouns.
    # An explicit naming/explanation construction supplies an additional span.
    named = re.findall(r"(?:^|[、。\s])([^、。！？?]+?)(?:って(?:知って|何|どんな)|を(?:説明|解説|知って)|とは|は何|知って)", text)
    nominal = re.findall(r"(?:^|[、。\s])([^、。！？?]+?)(?:について|はどんな|の(?:作者|歌手|発売|価格|値段|内容))", text)
    named += [span for span in nominal if len(span) >= 4 and all(
        t.part_of_speech.split(',')[0] in {'名詞', '接頭詞', '記号'} for t in _tokenizer().tokenize(span))]
    # Keep the largest spans (OVERDOSE must not become a separate target).
    candidates = sorted(set(explicit + latin + katakana + proper + named), key=lambda x: (-len(x), x))
    return [x for i, x in enumerate(candidates) if not any(normalize(x) in normalize(y) for y in candidates[:i])]


def subject_in(subject, evidence):
    subject, evidence = normalize(subject), normalize(evidence)
    if re.search(r'[a-z0-9]', subject):
        return bool(re.search(r'(?<![a-z0-9_])' + re.escape(subject) + r'(?![a-z0-9_])', evidence))
    return subject in evidence


def supports(query, evidence, subjects=()):
    q, e = normalize(query), normalize(evidence)
    if not e or UNCERTAIN.search(evidence):
        return False
    if subjects and not all(subject_in(s, e) for s in subjects):
        return False
    # A matching title/mention alone cannot establish an answer.
    remainder = e
    for subject in subjects:
        remainder = remainder.replace(normalize(subject), "")
    if len(re.sub(r"[\W_]", "", remainder)) < 4:
        return False
    for pattern, markers in FACETS.values():
        if re.search(pattern, q) and not any(normalize(m) in e for m in markers):
            return False
    terms = {normalize(t.base_form if t.base_form != "*" else t.surface)
             for t in _tokenizer().tokenize(query)
             if t.part_of_speech.startswith("名詞") and t.part_of_speech.split(",")[1] not in {"代名詞", "非自立", "数"}
             and t.surface not in GENERIC}
    covered = {term for term in terms if term in e or any(term in normalize(s) for s in subjects)}
    # Require all content nouns, rather than high recency/importance alone.
    return bool(subjects or terms) and terms <= covered


@dataclass(frozen=True)
class KnowledgeDecision:
    external_required: bool
    reliable_context: bool
    subjects: tuple[str, ...]
    evidence: tuple[str, ...]
    reason: str

    def to_dict(self):
        return asdict(self)


class KnowledgeGate:
    def evaluate(self, query, memory, state, previous_subjects=(), *, force_external=False):
        subjects = tuple(entities(query))
        requesting = bool(FACT_REQUEST.search(query))
        if not subjects and EXPLICIT_REQUEST.search(query) and (REFERENTIAL.search(query) or any(re.search(pattern, query) for pattern, _ in FACETS.values())):
            subjects = tuple(previous_subjects)
        # Bare names with a question marker and factual requests about names
        # both need evidence. Everyday reactions and personal plans do not.
        external = force_external or (requesting and bool(subjects))
        evidence = list(memory.reliable_context(query, subjects=subjects)) if external else []
        if external:
            for fact in state.active.values():
                if fact.status == Status.ACTIVE and fact.source in {SourceType.VERIFIED_MEMORY, SourceType.RUNTIME, SourceType.SYSTEM}:
                    text = f"{fact.key} = {fact.value}"
                    if supports(query, text, subjects):
                        evidence.append(text)
        return KnowledgeDecision(external and not evidence, bool(evidence), subjects, tuple(evidence),
                                 "missing_reliable_evidence" if external and not evidence else "supported" if evidence else "not_external_request")

    @staticmethod
    def unverified_reply():
        return "そこはまだ未確認。今は外部検索につながってないから、知ったふりで説明はできない。資料があれば、それをもとに一緒に考えられる。"
