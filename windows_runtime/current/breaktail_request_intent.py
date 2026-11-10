"""Detect an explicit user request without requiring a final question mark.

Use unquoted prose so a user's quoted example like 「直して」 is not
mistaken for a new command. The detector only classifies the current turn;
it does not authorize tool use.
"""
from __future__ import annotations
import re

# Requests explicitly ending a message. Do not match reported past events
# such as "友達が直してくれた".
_REQUEST_END = re.compile(
    r"(?:"
    r"(?:作|直|調べ|探|見|読|書|試|教|答|まとめ|説明|確認|比較|検証|評価|分析|実装|変更|修正|翻訳|設計|計算|提案|検索|整理|解説|追加|削除|更新|進め|聞かせ|見せ|出し|考え|手伝っ|話し|続け|実行し)"
    r"(?:て|いて)(?:くれ(?:よ)?|ください|ほしい|欲しい|よ|ね)?"
    r"|(?:どうすれば|どうしたら|どうやって|なんで|なぜ|何故|何を|何が|どうする|どうなる|どう思う|どう思ってる)"
    r"[^。！？!?\n]{0,35}"
    r"|(?:やって|やれよ|やってくれ|頼む|お願い|教えろ|答えろ|見せろ|作れ|直せ|調べろ)"
    r")"
    r"[。！？!?\s]*$"
)


def explicit_request(text: str) -> bool:
    # Remove full quoted passages and code before evaluating the active user
    # instruction. A quotation may contain a command but is not itself one.
    from breaktail_reply_contract import unquoted_prose
    candidate = unquoted_prose(text).strip()
    if not candidate:
        return False
    return bool(_REQUEST_END.search(candidate))
