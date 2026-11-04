"""Rule-only selection of optional Runtime Facts.  No model calls belong here."""

import re


RESIDENT_FACTS = {"clock", "capabilities", "operation"}

RULES = (
    ("system.identity", re.compile(r"(?:OS|Windows|Linux|macOS|Mac|パソコン|PC).{0,16}(?:何|種類|情報|環境|バージョン)|(?:何の|どの).{0,8}(?:OS|環境)|Python.{0,12}(?:バージョン|version)", re.I)),
    ("system.disk", re.compile(r"(?:ディスク|ドライブ|ストレージ).{0,16}(?:空き|容量|どれ|状態)|(?:空き|容量).{0,12}(?:ディスク|ドライブ|ストレージ)", re.I)),
    ("system.cpu", re.compile(r"(?:CPU|プロセッサ).{0,16}(?:何|数|コア|状態)|(?:何|いくつ).{0,12}(?:CPU|コア)", re.I)),
    ("system.memory", re.compile(r"(?<![A-Za-z0-9_])RAM(?![A-Za-z0-9_])|メモリ(?:使用|空き|余|容量)|system\s*memory", re.I)),
    ("service.ollama", re.compile(r"Ollama.{0,16}(?:生き|状態|接続|動い|reachable|health)|(?:生き|状態|接続).{0,16}Ollama", re.I)),
    ("service.web", re.compile(r"(?:Web|ウェブ).{0,12}(?:サーバ|server).{0,16}(?:状態|生き|接続|動い)|(?:Web|ウェブ)サーバ", re.I)),
    ("last_error", re.compile(r"(?:最後|直近|最新|さっき).{0,10}(?:エラー|error)|(?:エラー|error).{0,10}(?:状態|何|ある)", re.I)),
    ("memory.state", re.compile(r"(?:Memory|メモリ|記憶).{0,14}(?:何件|件数|保存数|最後に保存|状態)", re.I)),
    ("context.state", re.compile(r"(?:context|コンテキスト|履歴).{0,14}(?:状態|何件|件数|trim|トリム|残|使用)", re.I)),
    ("network.local", re.compile(r"(?:ローカル|localhost|127\.0\.0\.1).{0,14}(?:疎通|接続|ネットワーク|network)|network\s*state", re.I)),
)


def resolve_fact_groups(user_text: str) -> set[str]:
    selected = set(RESIDENT_FACTS)
    for group, pattern in RULES:
        if pattern.search(user_text):
            selected.add(group)
    return selected

