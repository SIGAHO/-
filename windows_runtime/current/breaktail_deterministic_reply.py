"""Direct, code-owned replies for narrowly explicit Breaktail questions.

This module has no persistence and never calls an LLM.  It deliberately returns
None for ordinary conversation so the normal model route remains authoritative.
"""

from __future__ import annotations

import re
from datetime import datetime

from breaktail_local_dictionary import local_definition_reply


_NON_QUESTION_CONTEXT = re.compile(r"コード|プログラム|HTML|JavaScript|翻訳|という|っていう|[「『`]")
_GREETING = re.compile(r"^(?:よお|よう|やあ|こんにちは|こんばんは|おはよう|どうも)[！!。？?]*$", re.I)
_ACKNOWLEDGEMENT = re.compile(r"^(?:うん|了解|りょ|おけ|OK|ok|ありがと(?:う)?|ありがとう)[！!。？?]*$", re.I)


def _facts(runtime_context: dict) -> dict:
    """Accept either a Runtime Context or the enclosing Self context."""
    context = runtime_context.get("runtime_context", runtime_context)
    return {item.get("key"): item for item in context.get("facts", []) if isinstance(item, dict)}


def _capabilities(runtime_context: dict, facts: dict) -> dict:
    if isinstance(runtime_context.get("capabilities"), dict):
        return runtime_context["capabilities"]
    value = facts.get("capabilities", {}).get("value")
    return value if isinstance(value, dict) else {}


def _ok(item: dict | None) -> bool:
    return isinstance(item, dict) and item.get("status") == "ok"


def _format_number(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _clock_reply(text: str, facts: dict) -> str | None:
    if _NON_QUESTION_CONTEXT.search(text):
        return None
    clock = facts.get("clock.current_datetime_iso")
    if not _ok(clock):
        return None
    now = datetime.fromisoformat(clock["value"])
    asks_year = bool(re.search(r"(?:今年|ことし|今|いま|現在).{0,5}(?:何年|なんねん)(?!生)", text))
    asks_date = bool(re.search(r"(?:今日|きょう|今|いま|現在).{0,8}(?:何月|何日|日付|なんがつ|なんにち)", text))
    asks_time = bool(re.search(r"(?:今|いま|現在|今日|きょう).{0,10}(?:何時|時刻|何分|何秒|なんじ|なんぷん|なんびょう)", text))
    asks_seconds = bool(re.search(r"(?:何秒|なんびょう)", text))
    asks_weekday = bool(re.search(r"(?:今日|きょう|今|いま|現在).{0,8}(?:何曜|曜日|なんよう)", text))
    if not (asks_year or asks_date or asks_time or asks_weekday):
        return None
    parts = []
    if asks_date:
        parts.append(f"今日は{now.year}年{now.month}月{now.day}日")
    elif asks_year:
        parts.append(f"今年は{now.year}年")
    if asks_time:
        clock_text = f"今は{now.hour}時{now.minute:02d}分"
        if asks_seconds:
            clock_text += f"{now.second:02d}秒"
        parts.append(clock_text)
    if asks_weekday:
        parts.append(f"今日は{'月火水木金土日'[now.weekday()]}曜日")
    return "、".join(parts) + "。"


def _timezone_reply(text: str, facts: dict) -> str | None:
    """Answer only a direct local-runtime timezone question from the clock fact."""
    if _NON_QUESTION_CONTEXT.search(text):
        return None
    if not re.search(r"(?:今|いま|現在|この).{0,8}(?:タイムゾーン|時間帯)", text, re.I):
        return None
    clock = facts.get("clock.current_datetime_iso")
    if not _ok(clock):
        return "この実行環境のタイムゾーンは今は取得できていない。"
    now = datetime.fromisoformat(clock["value"])
    offset = now.strftime("%z")
    formatted_offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    return f"この実行環境の現在のタイムゾーンは{formatted_offset}。"


def _operation_reply(text: str, facts: dict) -> str | None:
    if not re.search(r"(?:さっき|最後|直近).{0,12}(?:保存|操作|実行).{0,12}(?:成功|完了|でき|結果)|(?:保存|操作).{0,12}(?:成功|完了).{0,8}(?:した|してる|したか|[？?])", text):
        return None
    item = facts.get("operation.last_result")
    result = item.get("value") if _ok(item) else None
    if not isinstance(result, dict):
        return "確認できる実行・検証結果がないから、成功したとは言えない。"
    operation = result.get("operation", "operation")
    if result.get("successful") is True:
        return f"直近の「{operation}」は、実行後の検証まで成功してる。"
    if result.get("executed") is True and result.get("verified") is not True:
        return f"直近の「{operation}」は実行されたけど、検証できていないから成功したとは言えない。"
    return f"直近の「{operation}」は成功を確認できていない。"


def _self_preference_reply(text: str) -> str | None:
    """Give a small, revisable answer to an explicit question about Breaktail.

    This is deliberately not a stored personality claim, a user preference, or
    a general value-answering engine.  It only prevents the known empty
    ``I have no preferences`` fallback for a direct question about Breaktail.
    """
    if _NON_QUESTION_CONTEXT.search(text):
        return None
    direct_question = re.search(
        r"(?:お前|君|あなた|Breaktail).{0,16}(?:好み|好き嫌い).{0,12}(?:ない|ある|何|どう)(?:の|ん)?[？?？]?$",
        text,
        re.I,
    )
    if not direct_question:
        return None
    return (
        "ある。今の俺なら、相手が自分で決められて、分からないことを分からないまま話せる方が好き。"
        "ただ、固定の思想として押しつける気はないし、理由や証拠が変われば判断も変える。"
    )


def try_deterministic_reply(user_text: str, runtime_context: dict, history=None) -> str | None:
    """Return a direct reply for an explicit supported question, otherwise None."""
    text = user_text.strip()
    if not text:
        return None
    if _GREETING.fullmatch(text):
        return "よお。"
    if _ACKNOWLEDGEMENT.fullmatch(text):
        return "了解。"

    facts = _facts(runtime_context)
    capabilities = _capabilities(runtime_context, facts)
    clock = _clock_reply(text, facts)
    if clock:
        return clock

    timezone = _timezone_reply(text, facts)
    if timezone:
        return timezone

    preference = _self_preference_reply(text)
    if preference:
        return preference

    definition = local_definition_reply(text)
    if definition:
        return definition

    deterministic = runtime_context.get("runtime_context", runtime_context).get("deterministic")
    if isinstance(deterministic, dict) and isinstance(deterministic.get("answer_core"), str):
        return deterministic["answer_core"]

    operation = _operation_reply(text, facts)
    if operation:
        return operation

    # An explicit request to fetch current information must not reach 14B as
    # if a search had happened.  This route reports only the connected action
    # boundary; it never claims to have searched or starts an external action.
    search_action = bool(re.search(
        r"(?:ネット|web|ウェブ).{0,16}(?:検索|調べ).{0,24}(?:して|取って|持って)|"
        r"(?:検索|調べ).{0,24}(?:最新(?:情報|ニュース|価格)|結果).{0,12}(?:取って|持って|して)",
        text, re.I,
    ))
    if search_action:
        if capabilities.get("can_request_web_search_now") is True:
            return "検索アダプタは接続されているけど、この会話ではまだ検索を実行していない。"
        return "この会話経路には検索アダプタが接続されていないから、最新情報を取ってきたとは言えない。"

    if re.search(r"検索.{0,10}(?:でき|使え)|(?:でき|使え).{0,10}検索", text, re.I):
        return ("検索できる。" if capabilities.get("can_request_web_search_now") is True
                else "この会話経路には検索アダプタが接続されていない。")
    if re.search(r"(?:Vision|ビジョン|画面|スクリーン).{0,12}(?:見え|見れ|映|観察|でき)", text, re.I):
        state = capabilities.get("vision_state")
        if capabilities.get("can_observe_screen_now") is True:
            return "今回のVision結果は取得できている。"
        if state == "temporary_failed":
            return "Visionは接続されているけど、今回は取得に失敗している。"
        return "今は画面認識センサが接続されていないから、画面は見えない。"
    if re.search(r"ファイル.{0,12}(?:操作|保存|動か|でき)|(?:操作|保存).{0,12}ファイル", text):
        return ("接続されたファイル操作ツールで扱える。" if capabilities.get("can_request_file_operation_now") is True
                else "この会話経路にはファイル操作ツールが接続されていない。")
    if re.search(r"アバター.{0,12}(?:動か|移動|操作|でき)", text):
        return ("アバター移動を要求できる。" if capabilities.get("can_request_avatar_move_now") is True
                else "この会話経路にはアバター移動ツールが接続されていない。")

    if re.search(r"RAM.{0,12}(?:余|空き|どれ|状態)|(?:余|空き).{0,12}RAM", text, re.I):
        item = facts.get("system.memory")
        if not _ok(item) or not isinstance(item.get("value"), dict):
            return "RAMの空き容量は今は取得できていない。"
        value = item["value"]
        return f"RAMは{_format_number(value.get('available_gib'))} GiB空いていて、使用率は{_format_number(value.get('used_percent'))}% 。"
    if re.search(r"(?:OS|Windows|Linux|macOS|Mac|パソコン|PC).{0,16}(?:何|種類|情報|環境|バージョン)|(?:何の|どの).{0,8}(?:OS|環境)|Python.{0,12}(?:バージョン|version)", text, re.I):
        item = facts.get("system.identity")
        value = item.get("value") if _ok(item) else None
        if not isinstance(value, dict):
            return "OSや実行環境の情報は今は取得できていない。"
        return f"OSは{value.get('os')} {value.get('os_release')}、Pythonは{value.get('python')}。"
    if re.search(r"(?:ディスク|ドライブ|ストレージ).{0,16}(?:空き|容量|どれ|状態)|(?:空き|容量).{0,12}(?:ディスク|ドライブ|ストレージ)", text, re.I):
        item = facts.get("system.disk")
        value = item.get("value") if _ok(item) else None
        if not isinstance(value, dict):
            return "ディスク容量は今は取得できていない。"
        return f"{value.get('root')} の空きは{_format_number(value.get('free_gib'))} GiB、全体は{_format_number(value.get('total_gib'))} GiB。"
    if re.search(r"(?:CPU|プロセッサ).{0,16}(?:何|数|コア|状態)|(?:何|いくつ).{0,12}(?:CPU|コア)", text, re.I):
        item = facts.get("system.cpu")
        value = item.get("value") if _ok(item) else None
        if not isinstance(value, dict) or not isinstance(value.get("logical_count"), int):
            return "CPUの論理コア数は今は取得できていない。"
        return f"この実行環境から見えるCPU論理コア数は{value['logical_count']}。"
    if re.search(r"(?:Memory|メモリ|記憶).{0,12}(?:何件|件数|保存数)|(?:何件|件数).{0,12}(?:Memory|メモリ|記憶)", text, re.I):
        item = facts.get("memory.state")
        if not _ok(item) or not isinstance(item.get("value"), dict):
            return "Memory件数は今は取得できていない。"
        return f"Memoryは{item['value'].get('count')}件。"
    if re.search(r"(?:history|会話|履歴|conversation).{0,12}(?:何件|件数|数)|(?:何件|件数).{0,12}(?:history|会話|履歴|conversation)", text, re.I):
        item = facts.get("context.state")
        if not _ok(item) or not isinstance(item.get("value"), dict):
            return "会話履歴件数は今は取得できていない。"
        return f"会話履歴は{item['value'].get('history_message_count')}件。"
    if re.search(r"(?:直近|最後|最新|さっき).{0,10}(?:エラー|error)|(?:エラー|error).{0,10}(?:ある|何|状態)", text, re.I):
        item = facts.get("last_error")
        if not _ok(item):
            return "直近エラーは確認できていない。"
        errors = item.get("value", {}).get("errors", {})
        return "直近エラーはない。" if not errors else "直近エラーがある。"

    service_match = re.search(r"(Ollama|(?:Web|ウェブ)\s*(?:server|サーバ)).{0,12}(?:生き|状態|接続|動い|起動|reachable|health)", text, re.I)
    if service_match:
        key = "service.ollama" if service_match.group(1).lower() == "ollama" else "service.web"
        item = facts.get(key)
        if isinstance(item, dict) and item.get("status") == "not_connected":
            return f"{service_match.group(1)}には接続できていない。"
        if not _ok(item) or not isinstance(item.get("value"), dict):
            return f"{service_match.group(1)}の状態は今は確認できていない。"
        return (f"{service_match.group(1)}は生きている。" if item["value"].get("reachable") is True
                else f"{service_match.group(1)}には接続できていない。")
    return None
