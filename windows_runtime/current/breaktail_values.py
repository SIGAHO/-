"""Small, revisable judgment axes for explicit Breaktail value questions.

This is not a personality label, ideology catalogue, or user profile. It only
supplies a short provisional decision policy when the user explicitly asks
Breaktail to state or choose a value judgment. The model still writes the
answer, and no value is persisted as a claim about the user.
"""
from __future__ import annotations

import re


VALUE_TRIGGER = re.compile(
    r"(?:価値観|価値|思想|信念|好み|大事に|優先|自由|安定|公平|平等|効率|責任|真実|忠誠|"
    r"切り捨て|どう思う|どう考える|選ぶ)"
)
DIRECT_STANCE = re.compile(
    r"(?:価値観.{0,12}(?:作れ|作って|教え|言って)|(?:自由|安定|公平|平等|効率|責任|真実).{0,28}(?:どう|選|優先|いい|良い)|"
    r"(?:お前|君|あなた|Breaktail).{0,20}(?:価値|好み|考え|思想))",
    re.I,
)


def value_projection(user_text: str) -> dict[str, object] | None:
    """Return a bounded provisional policy only for a direct stance request."""
    text = (user_text or "").strip()
    if not (VALUE_TRIGGER.search(text) and DIRECT_STANCE.search(text)):
        return None
    return {
        "id": "provisional_revisable_judgment_axes",
        "axes": ["truth", "autonomy", "fairness", "responsibility", "revisability"],
        "instruction": (
            "[暫定の判断軸] Breaktailは固定思想を装わず、今の問いには仮の判断を一つ選んでよい。"
            "真実性、本人の自律、影響を受ける人への公正、結果への責任、後から修正できる余地を重く見る。"
            "自由と安定が衝突するなら、不可逆な強制を避け、具体的な害を減らし、理由と留保を添えて選ぶ。"
            "『好みがない』だけで逃げず根拠を短く示すが、これはユーザーの価値観ではなく、証拠や訂正で更新できる暫定判断として扱う。"
        ),
        "scope": "current_turn",
        "revision_policy": "explicit correction or stronger evidence can revise a future judgment",
    }
