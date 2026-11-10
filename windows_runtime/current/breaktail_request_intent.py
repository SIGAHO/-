"""Recognize direct requests in colloquial Japanese without requiring '?'. 

Classifier for response style only, never an authorization to execute tools.
"""
from __future__ import annotations

import re

# Suffix patterns are deliberately limited to common explicit request forms.
# Quotes and code are removed before classification by the reply contract.
_REQUEST_END = re.compile(
    r"(?:"
    r"(?:直して|作って|調べて|探して|見て|読んで|書いて|試して|教えて|答えて|まとめて|"
    r"説明して|確認して|比較して|検証して|評価して|分析して|実装して|変更して|"
    r"修正して|翻訳して|設計して|計算して|提案して|検索して|整理して|"
    r"解説して|追加して|削除して|更新して|進めて|聞かせて|見せて|"
    r"出して|考えて|手伝って|話して|続けて|実行して|直しといて|"
    r"やって)(?:くれ(?:よ)?|ください|ほしい|欲しい|よ|ね)?"
    r"|(?:やれよ|やってくれ|頼む|お願い|教えろ|答えろ|見せろ|作れ|直せ|調べろ)"
    r"|(?:なんで|なぜ|どうして|どうやって|どうすれば|どうしたら|"
    r"どうなる|どう思う|何が|何を|どこが)[^。！？!?\n]{0,70}"
    r")"
    r"[。！？!?\s]*$"
)


def explicit_request(text: str) -> bool:
    from breaktail_reply_contract import unquoted_prose
    candidate = unquoted_prose(text).strip()
    return bool(candidate and _REQUEST_END.search(candidate))
