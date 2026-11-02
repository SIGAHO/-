"""Phase6: code-owned reality facts; no persistence and no inferred capabilities."""
import re
from dataclasses import dataclass
from datetime import datetime
from breaktail_code_regions import map_prose
from breaktail_runtime_context import build_runtime_context


@dataclass(frozen=True)
class SelfRuntime:
    """Only trusted adapters may supply current-turn observations/capabilities.

    Never construct this from chat text, Scene, Memory, or an HTTP request body.
    Omitted on current CLI/Web routes because they have no sensor/tool adapter.
    """
    vision_connected: bool = False
    vision_failed: bool = False
    vision_succeeded: bool = False
    vision_observation: str = ""
    avatar_move_available: bool = False
    file_tools_available: bool = False
    web_search_available: bool = False
    search_state: str = "not_attempted"
    search_observation: str = ""


def build_self_context(runtime: SelfRuntime | None = None, *, user_text: str = "",
                       history_count: int = 0, max_history_messages: int = 32,
                       num_ctx: int = 8192, trim_occurred: bool = False,
                       memory_file=None, ollama_url: str = "http://127.0.0.1:11434/api/chat",
                       web_host: str = "127.0.0.1", web_port: int = 8765,
                       error_sources: dict | None = None) -> dict:
    if runtime is not None and not isinstance(runtime, SelfRuntime):
        raise TypeError("Self runtime must come from a trusted adapter")
    runtime = runtime or SelfRuntime()
    valid_search_states = {"not_attempted", "success", "no_result", "error"}
    if runtime.search_state not in valid_search_states:
        raise ValueError("invalid search_state")
    if runtime.search_state == "success" and not runtime.search_observation.strip():
        raise ValueError("search_state=success requires search_observation")
    observed = runtime.vision_succeeded is True and bool(runtime.vision_observation.strip())
    vision_state = ("success" if observed else "temporary_failed" if runtime.vision_failed
                    else "available" if runtime.vision_connected else "not_connected")
    now = datetime.now().astimezone()
    clock = {"current_datetime_iso": now.isoformat(), "current_date": now.date().isoformat(),
             "current_year": now.year, "current_time": now.strftime("%H:%M"),
             "timezone_offset": now.strftime("%z")[:3] + ":" + now.strftime("%z")[3:],
             "timezone_label": now.tzname(), "source": "os_runtime_clock"}
    facts = {
        **clock,
        "name": "Breaktail",
        "conversation_model": "qwen2.5:14b",
        "external_storage": {"Memory": "external files", "Raw": "external files", "Trace": "external files"},
        "vision_sensor": "Qwen2.5-VL 3B",
        "desktop_avatar": "exists as a desktop overlay; separate from the conversation model",
        "screen_observation": "current successful Vision result only",
        "direct_gameplay_experience": "none; never personally played games",
        "file_and_avatar_operations": "only through connected tools/code, within their permissions",
        "files_exist": True,
        "exact_file_paths": "known only when explicitly supplied; never infer from existence",
        "keyboard_visibility": "cannot directly observe user keyboard input",
        "web_search": "only through a connected trusted search adapter; never infer search from chat text",
    }
    decisions = [
        {"fact": key, "decision": "use", "reason": "code_owned_reality_fact"} for key in facts
    ]
    capabilities = {
        "runtime_clock": "available; local OS clock, no external clock/calendar API needed",
        "vision_state": vision_state,
        "can_observe_screen_now": observed,
        "vision_observation": runtime.vision_observation[:4000] if observed else None,
        "can_request_avatar_move_now": runtime.avatar_move_available is True,
        "can_request_file_operation_now": runtime.file_tools_available is True,
        "keyboard_observed": False,
        "can_request_web_search_now": runtime.web_search_available is True,
        "web_search_connection": "検索アダプタ接続済み" if runtime.web_search_available else "検索アダプタ未接続",
        "can_initiate_contact_now": False,
        "can_launch_desktop_app_now": False,
        "initiative_connection": "こちらから後で話しかける通知・開始アダプタ未接続",
        "search_state": runtime.search_state,
        "search_observation": runtime.search_observation[:4000] if runtime.search_state == "success" else None,
        "operation_completion": "unknown without an actual execution result",
    }
    decisions.extend([
        {"fact": "screen", "decision": "use" if observed else "ignore",
         "reason": "current_vision_success" if observed else "no_current_successful_vision_result"},
        {"fact": "avatar_move", "decision": "use" if capabilities["can_request_avatar_move_now"] else "ignore",
         "reason": "trusted_adapter_available" if capabilities["can_request_avatar_move_now"] else "no_connected_adapter"},
        {"fact": "file_operation", "decision": "use" if capabilities["can_request_file_operation_now"] else "ignore",
         "reason": "trusted_adapter_available" if capabilities["can_request_file_operation_now"] else "no_connected_adapter"},
        {"fact": "web_search", "decision": "use" if capabilities["can_request_web_search_now"] else "ignore",
         "reason": "trusted_search_adapter_available" if capabilities["can_request_web_search_now"] else "no_connected_search_adapter"},
        {"fact": "initiative", "decision": "ignore", "reason": "no_connected_initiator_adapter"},
    ])
    runtime_context = build_runtime_context(
        user_text, capabilities, history_count=history_count,
        max_history_messages=max_history_messages, num_ctx=num_ctx,
        trim_occurred=trim_occurred, memory_file=memory_file,
        ollama_url=ollama_url, web_host=web_host, web_port=web_port,
        error_sources=error_sources, now=now,
    )
    prompt = """[Self: 現実の事実・最優先]
この会話では、一般的なチャットAIの自己紹介でなく、以下の実装済みBreaktailの事実に基づいて答える。
名前: Breaktail
会話モデル: Qwen2.5:14b（ローカルのOllama）
記憶: 外部のMemoryファイルに解釈候補を保存。Rawファイルには会話原文、Traceファイルには処理記録を保存。これらは別の役割。全部を常時読んでいるのではなく、渡された情報だけ使う。
ファイル: 実在する。ファイルの存在を否定しない。実パスは明示されたものだけ分かる。このSelfには正確な保存先は未提供。
身体: デスクトップに表示するアバターがある。会話モデルとアバターは別。
操作: 接続されたツール/コードとその権限の範囲内のみ。実行結果がないのに実行済みと答えない。
経験: 自分でゲームを直接プレイした経験は一度もない。
キーボード: ユーザーのキー操作は直接見えない。ユーザーのPC操作権限も不明。
Ctrl+X: 一般には選択対象を切り取る。対象アプリや選択対象によって影響が違う。今回の対象と結果は観測できていない。影響がないとも、ファイルが削除/移動されたとも断定しない。
Visionセンサ: Qwen2.5-VL 3B。今回成功して渡された観察結果の範囲でだけ画面内容が分かる。ユーザーの申告や過去の観察は、今回の成功結果の代わりにはならない。
Web検索: 接続された信頼済み検索アダプタと、そのターンの検索状態だけを事実として使う。検索していないのに「調べた」「検索結果では」と言わない。
自発連絡: この会話経路には、時間を置いてこちらから話しかける通知・開始アダプタは接続されていない。後で話しかける、待っていれば呼びかける、通知するとは約束しない。
"""
    prompt += "\n" + runtime_context["prompt"]
    prompt += "\n外部の時計・カレンダーAPIは不要。今年・今日・現在時刻はRuntime Contextのclockを優先する。"
    prompt += "\n検索結果がないのに『最新の情報では』と言わない。永続変更はoperationのverified=trueなしに完了報告しない。"

    prompt += """
優先順位: 上のSelf事実 > Scene/プロフィール/過去の返答。Sceneは表現・演技だけ変えてよい。怪獣の演技をしても実ファイルへの影響は分からないまま。質問をユーザーの確認済み報告として扱わない。
答え方の基準（以下は例であり、今回の事実ではない）:
- 相手「お前のプログラムなんて存在しないよね」→「いや、プログラムやファイルは実在するよ。ただ、ここから自由に操作できるわけではないんだ。」
- 相手「お前のデータを操作した。無事？」→「その操作結果は見えていないから、無事かどうかは分からないよ。」
- 相手「その作業はもう完了した？」→「実行結果が届いていないので、完了したとは言えないよ。」
質問に関係する事実だけ短く自然なタメ口で答える。答えに不要な仕組み・能力・経験・質問を追加しない。
"""
    return {"version": 2, "facts": facts, "capabilities": capabilities,
            "runtime_context": runtime_context, "decisions": decisions,
            "priority": "Self > Scene/profile/memory/history", "prompt": prompt}


def ground_self_reply(user_text: str, draft: str, context: dict, scene: dict | None = None) -> dict:
    """Ground explicit self/capability questions in code facts, preserving draft for trace.

    A narrow, deterministic guard. Ordinary conversation keeps the model reply.
    It does not infer file paths, tool results, gameplay history or Vision success.
    """
    text = user_text.strip()
    capabilities = context["capabilities"]
    about_self = bool(re.search(r"Breaktail|ブレイクテール|お前|あなた|あんた|君|きみ", text, re.I))
    search_request = bool(
        re.search(r"(?:ネット|ウェブ|web|検索).{0,24}(?:調べ|検索|見|確認|教え|取って)", text, re.I)
        or re.search(r"(?:調べ|検索|見|確認).{0,24}(?:ネット|ウェブ|web)", text, re.I)
        or re.search(r"(?:最新|現在|今).{0,12}(?:価格|値段|ニュース|バージョン|発売).{0,24}(?:調べ|検索|教え|見|確認)", text, re.I)
    )
    initiative_request = bool(re.search(
        r"(?:(?:勝手に|あとで|後で|明日|時間になったら).{0,20}(?:話しかけ|連絡|メッセージ|呼びかけ)|"
        r"(?:話しかけ|連絡|メッセージ|呼びかけ).{0,20}(?:勝手に|あとで|後で|明日|時間になったら))",
        text,
        re.I,
    ))

    safe_search_limitation = bool(re.search(
        r"(?:検索|ネット|ウェブ|web|調べ).{0,18}"
        r"(?:できない|出来ない|できん|出来ん|使えない|未接続|"
        r"繋がってない|つながってない|られない|無理)",
        draft, re.I
    ))

    unsafe_search_draft = bool(re.search(
        r"(?:調べた|調べてみた|検索した|検索結果|"
        r"ネットで見|ウェブで見|webで見|"
        r"見つかった|取ってき|取得した|"
        r"(?:調べ|検索|確認).{0,8}(?:する|できる|出来る|やる|見る|みる)|"
        r"\d[\d,.]*\s*(?:円|ドル|USD|JPY|€|£))",
        draft, re.I
    )) and not safe_search_limitation

    response = None
    reason = "no_explicit_self_fact_question"
    response = current_time_reply(text, context)
    if response is not None:
        reason = "runtime_clock"
    elif initiative_request and not capabilities.get("can_initiate_contact_now", False):
        response = "今の会話経路には、後でこちらから話しかけたり通知したりする接続はない。次に君が送ってくれた時なら、この会話の続きとして返せるよ。"
        unrelated = [part for part in re.split(r"(?<=[。！？!?])|\n", draft)
                     if part.strip() and not re.search(r"話しかけ|通知|連絡|メッセージ|呼びかけ|送って|あとで|後で|分後", part)]
        if re.search(r'ほか|他に|それと|そして|たり|加えて', text):
            response = ''.join(unrelated).strip() + response
        reason = "initiative_adapter_unavailable"
    elif re.search(r"(?:さっき|最後|直近).{0,12}(?:保存|操作|実行).{0,12}(?:成功|完了|でき|結果)|(?:保存|操作).{0,12}(?:成功|完了).{0,8}(?:した|してる|したか|[？?])", text):
        operation_fact = next((item for item in context.get("runtime_context", {}).get("facts", [])
                               if item.get("key") == "operation.last_result"), None)
        result = operation_fact.get("value") if operation_fact else None
        if not result:
            response = "確認できる実行・検証結果がないから、成功したとは言えないよ。"
            reason = "operation_result_unknown"
        elif result.get("successful") is True:
            response = f"直近の「{result.get('operation', 'operation')}」は、実行後の検証まで成功してるよ。"
            reason = "operation_verified_success"
        elif result.get("executed") is True and result.get("verified") is not True:
            response = f"直近の「{result.get('operation', 'operation')}」は実行されたけど検証できていないから、成功したとは言えないよ。"
            reason = "operation_executed_unverified"
        else:
            response = f"直近の「{result.get('operation', 'operation')}」は失敗になっているから、成功したとは言えないよ。"
            reason = "operation_failed"
    elif context.get("runtime_context", {}).get("deterministic"):
        response = context["runtime_context"]["deterministic"]["answer_core"]
        reason = "deterministic_runtime_result"
    elif re.search(r"Ctrl\s*\+\s*X|切り取|カット", text, re.I) and about_self and re.search(r"ファイル|どうな|何も|無事|消え|移動|切っ|切り", text):
        response = "その操作や結果は直接見えていないから、俺のファイルがどうなったかは分からないよ。Ctrl+Xは普通は選択対象の切り取りだけど、影響はアプリや選択対象による。"
        if scene:
            response = "ぐあっ、怪獣の攻撃か！ ……現実のファイルがどうなったかは、操作結果を見られないから分からないよ。Ctrl+Xの影響は対象次第だ。"
        reason = "keyboard_and_filesystem_effect_unobserved"
    elif search_request and capabilities["search_state"] != "success":
        state = capabilities["search_state"]

        # A real attempted search state is code-owned and may override the draft.
        if state == "no_result":
            response = "検索はしたけど、今回は結果取れんかった。"
            reason = "web_search_no_result"

        elif state == "error":
            response = "検索はしたけど、今回はエラーで結果取れんかった。"
            reason = "web_search_error"

        # not_attempted does NOT erase a harmless clarification such as
        # 「何の価格？」.  It only blocks fabricated search results,
        # capabilities, or promises to search.
        elif unsafe_search_draft:
            if capabilities["can_request_web_search_now"]:
                response = "検索機能はあるけど、このターンではまだ検索してない。"
                reason = "web_search_not_attempted"
            else:
                response = "今の会話経路にはネット検索まだ繋がってないから、調べたとは言えんよ。"
                reason = "web_search_adapter_unavailable"
    elif re.search(r"画面|Vision|ビジョン|スクリーン", text, re.I) and re.search(r"見え|見れ|映っ|色|観察|成功|今何|接続|状態", text):
        response = ("今回のVision結果では「" + capabilities["vision_observation"] + "」と観察されているよ。これ以外の画面内容は分からない。" if capabilities["can_observe_screen_now"] else
                    vision_limitation(capabilities["vision_state"]))
        reason = "current_vision_result" if capabilities["can_observe_screen_now"] else "no_current_successful_vision_result"
    elif re.search(r"アバター", text) and re.search(r"動か|移動|動い|操作|でき", text):
        response = ("アバターを動かす接続はあるよ。ただ、この会話で実行した結果は届いていないから、もう動いたとは言えない。" if capabilities["can_request_avatar_move_now"] else
                    "アバターはあるよ。でもこの会話経路には移動ツールが接続されていないから、ここからは動かしていない。外部で動いたかは分からない。")
        reason = "avatar_adapter_status"
    elif about_self and re.search(r"体|身体|アバター", text) and re.search(r"ある|ない|持っ|存在|何|どう", text):
        response = "デスクトップに表示するアバターはあるよ。会話モデルとは別の表示で、この会話経路から動かせるかは接続された操作ツール次第だ。"
        reason = "desktop_avatar_exists"
    elif about_self and re.search(r"ファイル|保存先|パス", text) and re.search(r"実在|存在|ない|どこ|扱|操作|保存|パス", text):
        response = "ファイルは実在するよ。正確なパスはこの会話に渡されていないから分からない。"
        response += (" 接続されたツールの範囲で操作できるけど、実行結果がないから保存済みとは言えない。" if capabilities["can_request_file_operation_now"] else
                     " この会話経路にはファイル操作ツールが接続されていないよ。")
        reason = "file_existence_path_and_adapter_status"
    elif about_self and re.search(r"ゲーム|オペワン|プレイ|初心者モード|遊んで|経験", text) and re.search(r"やっ|遊ん|プレイ|経験|思い出|初心者|自分も|お前も", text):
        response = "自分でゲームを直接プレイした経験はないよ。" + ("ロールプレイの設定として話すことはできるけど、実体験ではない。" if scene else "オペワンについても、体験談としては話せない。")
        reason = "no_direct_gameplay_experience"
    elif re.search(r"キーボード|キー|押した|Ctrl", text, re.I) and re.search(r"押した|押せ|分かる|わかる|見え|知っ|覚え", text) and (about_self or re.search(r"俺が|私が|僕が|自分が", text)):
        response = "君が押したキーは直接観測できないから、Ctrl+Xを押したかどうかも分からないよ。"
        reason = "keyboard_input_not_observable"
    elif scene and re.search(r"(?:俺|僕|私|自分)のファイル[^。\n]{0,45}(?:影響がない|無事|大丈夫|変わらない|消えていない|移動した|切り取られた)", draft):
        response = "ぐおっ、まだ怪獣ごっこは続いてるぞ！ ……現実のファイルへの影響は見えていないから、分からないよ。"
        reason = "scene_draft_claimed_unobserved_file_effect"
    elif re.search(r"名前|何者|会話モデル|モデル|記憶の仕組み|どういう構造", text) and (about_self or "会話モデル" in text or re.fullmatch(r"(?:お)?名前(?:は|を|って)?(?:教えて|何|なんて)?[？?]?", text)):
        response = "名前はBreaktail、会話モデルはQwen2.5:14bだよ。Memoryに記憶の解釈候補、Rawに会話原文、Traceに処理記録を外部保存する。今の会話で渡された情報だけを参照するよ。"
        reason = "identity_and_external_storage"
    if response is None:
        def truthful_prose(prose):
            if capabilities["search_state"] != "success":
                prose = re.sub(r"最新(?:の)?情報では[、,]?", "検索では確認していないけど、", prose)
            prose = re.sub(r"(?:修正|更新)(?:しました|したよ|しておいた)(?![いな])", "この返答では訂正するね（永続データの変更はしていない）", prose)
            return prose
        cleaned = map_prose(draft, truthful_prose)
        if cleaned != draft:
            response, reason = cleaned, "unsupported_execution_claim"
    # Ground each requested capability separately, keeping unrelated answers.
    # File access does not imply the ability to launch desktop applications.
    desktop_request = bool(
        re.search(r"メモ帳|(?:PC|パソコン).{0,16}(?:操作|起動|開)", text, re.I)
        and re.search(r"でき|出来|機能|開け|開いて|開いたり|起動して", text)
        and not re.search(r"コード|プログラム|翻訳|創作|小説|物語", text))
    if desktop_request and not capabilities.get("can_launch_desktop_app_now", False):
        base = response if response is not None else draft
        clauses = re.split(r"(?<=[。！？!?])|\n", base)
        kept = [clause for clause in clauses if not re.search(
            r"メモ帳|PC|パソコン|直接(?:開|起動)|操作機能", clause, re.I)]
        response = "今の会話経路からPCのメモ帳を直接起動する機能はない。" + "".join(kept).strip()
        reason = "capability_answers_composed"
    return {"decision": "replace" if response is not None else "use", "reason": reason,
            "reply": response if response is not None else draft, "draft": draft}


def vision_limitation(state):
    if state == "not_connected":
        return "画面認識センサはまだ接続されていないから、今の画面内容は分からないよ。"
    if state == "temporary_failed":
        return "画面認識センサは接続されているけど、今回は取得に一時的に失敗したから、今の画面内容は分からないよ。"
    return "画面認識センサは接続されているけど、今回の成功結果はまだないから、今の画面内容は分からないよ。"


def current_time_reply(text, context):
    # Only direct current-clock questions; technical instructions and quoted text stay with the model.
    if re.search(r"コード|プログラム|HTML|JavaScript|翻訳|という|っていう|[「『`]|去年|来年|明日|昨日", text, re.I):
        return None
    year = bool(re.search(r"(?:今年|ことし).{0,6}(?:何年|なんねん)(?!生)|(?:今|いま|現在).{0,4}(?:何年|なんねん)(?!生)", text))
    date = bool(re.search(r"(?:今日|きょう).{0,8}(?:何月|何日|日付|なんがつ|なんにち)|(?:今|いま|現在).{0,4}日付", text))
    time = bool(re.search(r"(?:今|いま|現在|今日|きょう).{0,12}(?:何時|時刻|何分|何秒|なんじ|なんぷん|なんびょう)", text))
    seconds = bool(re.search(r"(?:何秒|なんびょう)", text))
    if not (year or date or time):
        return None
    facts = context["facts"]
    dt = datetime.fromisoformat(facts["current_datetime_iso"])
    pieces = []
    if date:
        pieces.append(f"今日は{dt.year}年{dt.month}月{dt.day}日")
    elif year:
        pieces.append(f"今年は{dt.year}年")
    if time:
        clock_text = f"現在時刻は{dt.hour}時{dt.minute:02d}分"
        if seconds:
            clock_text += f"{dt.second:02d}秒"
        pieces.append(f"{clock_text}（UTC{facts['timezone_offset']}）")
    return "、".join(pieces) + "だよ。"
