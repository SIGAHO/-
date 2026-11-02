"""Small, code-owned session state for free conversation.

The state deliberately contains only the five Phase 7.13 fields.  Updates are
deterministic and conservative: if a sentence does not clearly change one of
them, the previous value is retained.
"""

from __future__ import annotations

import re


def new_working_state() -> dict:
    return {
        "topic": None,
        "mode": {"type": None, "persona": None, "active": False, "constraints": []},
        "entities": [],
        "corrections": [],
        "pending": [],
        "register": {"style": None, "turn": None, "source": None},
    }


def normalize_working_state(value: dict | None) -> dict:
    state = value if isinstance(value, dict) else new_working_state()
    defaults = new_working_state()
    for key, default in defaults.items():
        valid = isinstance(state.get(key), type(default))
        if key == "topic":
            valid = state.get(key) is None or isinstance(state.get(key), str)
        if key not in state or not valid:
            state[key] = default
    mode = state["mode"]
    for key, default in defaults["mode"].items():
        valid = isinstance(mode.get(key), type(default))
        if key in {"type", "persona"}:
            valid = mode.get(key) is None or isinstance(mode.get(key), str)
        if key not in mode or not valid:
            mode[key] = default
    return state


def _upsert(items: list[dict], key: str, value: dict) -> None:
    items[:] = [item for item in items if item.get(key) != value.get(key)]
    items.append(value)


def recent_entity_states(state: dict | None) -> list[dict]:
    """Return only explicitly resolved entity transitions for prompt/Trace use."""
    state = normalize_working_state(state)
    return [
        {key: item[key] for key in ("name", "kind", "state", "state_text", "turn") if key in item}
        for item in state["entities"][-4:]
        if item.get("kind") == "consumable" and item.get("state")
    ]


def update_working_state(state: dict | None, user_text: str, turn: str | int | None = None) -> dict:
    """Update the five-field state in place and return it."""
    state = normalize_working_state(state)
    text = (user_text or "").strip()
    compact = re.sub(r"\s+", "", text)
    mode = state["mode"]

    if re.search(r"(?:ロールプレイ|RP|なりきり|ごっこ)(?:を)?(?:終了|終わり|やめ)", compact, re.I):
        mode.update(type=None, persona=None, active=False, constraints=[])
    elif re.search(r"(?:ロールプレイ|RP|なりきり|ごっこ)(?:を)?(?:開始|始め|しよう|やろう|して)", compact, re.I):
        persona_match = re.search(r"([一-龯ぁ-んァ-ヶA-Za-z0-9_ー]{1,20})(?:系|風)?(?:の)?(?:ロールプレイ|RP|役)", compact, re.I)
        persona = persona_match.group(1) if persona_match else mode.get("persona")
        mode.update(type="roleplay", persona=persona, active=True)
        constraints = []
        if "自然に依存" in compact:
            constraints.append("違和感なく依存を感じさせる。拘束や孤立化はしない")
        mode["constraints"] = constraints

    # Explicit semantic corrections.  Newer entries replace older entries for
    # the same term, so they override stale interpretations in history.
    correction = None
    natural = re.search(
        r"自然に(?:っていうのは|というのは|は|=)(.+?)(?:って話|という意味|の意味)(?:で|、|。|$).{0,20}?(?:植物の自然)(?:じゃない|ではない)",
        compact,
    )
    if natural:
        correction = {"term": "自然に", "wrong": "植物の自然", "right": natural.group(1),
                      "turn": turn, "scope": "session"}
    else:
        simple = re.search(r"([^、。\s=]{1,20})(?:っていうのは|というのは|=)([^、。]{1,40})(?:という意味|って意味|って話)?", text)
        if simple:
            correction = {"term": simple.group(1).strip(), "wrong": None,
                          "right": simple.group(2).strip(), "turn": turn, "scope": "session"}
    if correction:
        _upsert(state["corrections"], "term", correction)

    # Register is explicit user preference, not an inference from the user's own
    # wording. A newer explicit preference replaces the prior one.
    if re.search(r"(?:敬語(?:を)?やめ|タメ口(?:で)?(?:話して|でいい)|普通(?:に)?話して)", compact, re.I):
        state["register"] = {"style": "casual", "turn": turn, "source": "explicit_user_request"}
    elif re.search(r"(?:今後|これから|ずっと)?.{0,8}敬語(?:で)?(?:話して|でお願い|にして)", compact, re.I):
        state["register"] = {"style": "polite", "turn": turn, "source": "explicit_user_request"}

    other = re.search(r"(?:君|きみ|お前|あなた)(?:と)?じゃなく(?:て)?[、, ]*([一-龯ぁ-んァ-ヶA-Za-z0-9_ー]{1,24}?)(?:ってやつ)?と", compact)
    if other:
        name = other.group(1)
        _upsert(state["entities"], "name", {
            "name": name,
            "description": "ユーザーが今回の同行相手として言及した人物",
            "confidence": "explicit_user_wording",
            "turn": turn,
        })
        _upsert(state["corrections"], "term", {
            "term": "今回の同行相手", "wrong": "Breaktail", "right": name,
            "turn": turn, "scope": "session",
        })

    # A minimal state transition is justified by the observed food-state rewind:
    # we retain only an explicit named consumable and its newest direct state.
    wants_food = re.search(r"(?P<name>[一-龯ぁ-んァ-ヶA-Za-z0-9ー]{2,30}?)(?:を|は)?食べたい", compact)
    ate_food = re.search(
        r"(?:(?P<name>[一-龯ぁ-んァ-ヶA-Za-z0-9ー]{2,30}?)(?:を|は))?"
        r"(?:もう|すでに)?食べ(?:てる|ている|ました|た)(?:[。！!？?]|$)",
        compact,
    )
    if wants_food:
        _upsert(state["entities"], "name", {
            "name": wants_food.group("name"), "kind": "consumable",
            "state": "want_to_eat", "state_text": "食べたい", "turn": turn,
        })
    elif ate_food:
        name = ate_food.group("name")
        if not name:
            previous = next((item for item in reversed(state["entities"])
                             if item.get("kind") == "consumable"), None)
            name = previous.get("name") if previous else None
        if name:
            _upsert(state["entities"], "name", {
                "name": name, "kind": "consumable",
                "state": "already_eaten", "state_text": "すでに食べている", "turn": turn,
            })

    if "ブラックジャック" in compact:
        state["topic"] = "ブラックジャックのコード作成と実行"
    elif re.search(r"焼き肉|焼肉", compact):
        state["topic"] = "友達との焼き肉"
    return state


def confirmed_facts(state: dict) -> list[str]:
    state = normalize_working_state(state)
    facts = []
    for item in state["corrections"][-6:]:
        if item.get("term") and item.get("right"):
            if item.get("wrong"):
                facts.append(f"{item['term']} = {item['right']}（{item['wrong']}ではない）")
            else:
                facts.append(f"{item['term']} = {item['right']}")
    for item in state["entities"][-4:]:
        if item.get("kind") == "consumable" and item.get("name") and item.get("state_text"):
            if item.get("state") == "already_eaten":
                facts.append(f"{item['name']} = {item['state_text']}（食べたいという古い状態ではない）")
            else:
                facts.append(f"{item['name']} = {item['state_text']}")
            continue
        if item.get("name") and item.get("description"):
            facts.append(f"{item['name']} = {item['description']}")
    return facts
