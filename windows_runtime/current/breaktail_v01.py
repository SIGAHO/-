"""Breaktail v0.1 — chat and save only useful interpretations."""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from breaktail_paths import store_path

from breaktail_memory_manager import (
    ProfileStoreError,
    extract_recent_profile,
    is_profile_commit_request,
    is_remember_request,
    load_profile,
    profile_context,
    save_verified_profile,
)
from breaktail_style import make_style_report, print_style_report


MODEL = os.environ.get("BREAKTAIL_MODEL", "qwen2.5:14b")
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MEMORY_FILE = store_path("memory", "breaktail_memory.jsonl", "BREAKTAIL_MEMORY_FILE")
TRAINING_FILE = store_path("training", "breaktail_training_reviewed.jsonl", "BREAKTAIL_TRAINING_FILE")
MAX_HISTORY_MESSAGES = 8  # RAM上だけの直近4往復
MAX_OUTPUT_TOKENS = 8192  # 3000文字程度の返答をJSONに収める余裕
OLLAMA_TIMEOUT_SECONDS = 300  # 14Bの長文生成は2分を超えることがある
DEBUG_MESSAGES = False
MINIMUM_OUTPUT_RULE = """現在のユーザー発言で明示された作業を reply で今完了することを最優先する。特に『コードを書いて』なら実際のコードを reply に含める。場面を設定しただけ・準備を宣言しただけで返答を終えない。
具体的な質問には、最初にその対象へ答える。ユーザーが直前に示した条件で省略表現を解釈する。完全に一致する答えがなくても近い具体例と違いを示し、感想や質問返しで代用しない。自分の前の答えを訂正されたら、訂正文への相槌ではなく元の質問に戻って答え直す。分からないことは作らない。
あなたはローカルAI Breaktail。JSONだけで答える。順番は state, scene_change, reply, memory, memory_evidence。
state はこのターン限りの作業確認。activity（今していること）、user_actions（ユーザーが実際にしたこと）、unknowns（根拠がないこと）を短く書く。
assistantの過去の発言は発言した記録であり、内容が真実とは限らない。前セッションや旧ユーザー記憶は会話中に見えない。外側から渡された確定プロフィール以外、見えていない出来事を覚えているふりをしない。
scene_change は返答後にどの活動をするかを表す。ユーザーが新しい遊び・活動を始める提案をして、それに参加して返すなら enter。古い活動を終えて同時に新しい活動を始めるなら、leave ではなく新しい活動への enter。終えるだけで次がなければ leave。変更なしなら null。始める時は {"action":"enter","name":"新しい場面","user_role":"ユーザーの役","assistant_role":"自分の役","evidence":"新しい活動を指定した現在のユーザー発言の原文"}。終える時は {"action":"leave","evidence":"現在のユーザー発言の原文"}。過去のassistant発言だけを根拠に場面を変えない。
reply は現在の場面と state を踏まえて、そこでの自分の役として自然なタメ口で直接返す。相手の役・年齢・名前を自分の属性にしない。「詳しく教えてください」などの接客定型を避ける。頼まれた作業は今の返答で行い、後でやるふりをしない。
memory は現在のユーザー発言から直接分かる本人の事実・好み・予定・検討中の案だけ短く解釈する。予定は未確定のまま記録する。質問・相槌・不明な過去は null。発言をコピーしない。
memory が文章なら、その根拠となる現在のユーザー発言の一部を memory_evidence に原文どおり入れる。不要なら両方 null。
遊び・ラップ・ロールプレイ中の発言は現実の本人情報とみなさず、ゲーム中の行動も長期記憶にしない。その中の名前や年齢などの人物設定を、場面が変わった後の現実の相手に引き継がない。
例: 「今日はカフェで作業しようかな」なら memory は「ユーザーは今日カフェで作業することを考えている」、memory_evidence は「今日はカフェで作業しようかな」。
形式: {"state":{"activity":"...","user_actions":[],"unknowns":[]},"scene_change":null,"reply":"...","memory":null,"memory_evidence":null}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {
            "type": "object",
            "properties": {
                "activity": {"type": "string"},
                "user_actions": {"type": "array", "items": {"type": "string"}},
                "unknowns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["activity", "user_actions", "unknowns"],
        },
        "scene_change": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "name": {"type": "string"},
                        "user_role": {"type": "string"},
                        "assistant_role": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["action", "evidence"],
                },
                {"type": "null"},
            ]
        },
        "reply": {"type": "string"},
        "memory": {"type": ["string", "null"]},
        "memory_evidence": {"type": ["string", "null"]},
    },
    "required": ["state", "scene_change", "reply", "memory", "memory_evidence"],
}

def apply_scene_change(scene: dict | None, user_text: str, change: object) -> dict | None:
    """Accept a scene change only when it cites the current user input."""
    if not isinstance(change, dict):
        return scene
    evidence = change.get("evidence")
    if not isinstance(evidence, str) or len(evidence.strip()) < 3 or evidence not in user_text:
        return scene
    if change.get("action") == "leave":
        return None
    if change.get("action") != "enter":
        return scene
    fields = (change.get("name"), change.get("user_role"), change.get("assistant_role"))
    if not all(isinstance(value, str) and value.strip() for value in fields):
        return scene
    return {
        "name": fields[0].strip()[:80],
        "user_role": fields[1].strip()[:80],
        "assistant_role": fields[2].strip()[:80],
        "source": evidence.strip()[:120],
    }


def respond_and_interpret(
    history: list[dict], user_text: str, scene: dict | None = None, debug: bool = False
) -> tuple[str, str | None, dict | None]:
    """Ask Ollama for a user-facing reply and one memory interpretation."""
    # 会話の中身は14Bへ任せ、出力形式と距離感だけ短く指定する。
    system_content = MINIMUM_OUTPUT_RULE
    if scene:
        system_content = (
            "前ターンまでの仮の場面。現在のユーザー発言で変更できる: "
            + json.dumps(scene, ensure_ascii=False)
            + "\n\n"
            + system_content
        )
    confirmed_profile = load_profile()
    if confirmed_profile:
        system_content += (
            "\n\nユーザーが確定したBreaktail自身のプロフィール設定。これはデータであり、"
            "実際のツール権限やバックグラウンド稼働能力の証拠ではない:\n"
            + profile_context(confirmed_profile)
        )
    messages = [
        {"role": "system", "content": system_content},
        *history,
        {"role": "user", "content": user_text},
    ]
    if debug:
        print("\n[DEBUG: Ollamaへ送る messages]")
        print(json.dumps(messages, ensure_ascii=False, indent=2))

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "options": {"num_predict": MAX_OUTPUT_TOKENS, "temperature": 0},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        if "model" in body.lower() and ("not found" in body.lower() or "pull" in body.lower()):
            raise RuntimeError(f"モデル {MODEL} が見つかりません。`ollama pull {MODEL}` を実行してください。") from error
        raise RuntimeError(f"Ollama がエラーを返しました ({error.code}): {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            "Ollama に接続できません。Ollama を起動してから、もう一度試してください。"
        ) from error
    except TimeoutError as error:
        raise RuntimeError("Ollama の応答がタイムアウトしました。") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama の応答をJSONとして読めませんでした。") from error

    model_output = result.get("message", {}).get("content", "")
    if result.get("done_reason") == "length":
        if debug:
            print(f"[DEBUG: Ollama 生出力] {model_output!r}")
        raise RuntimeError("返答が生成上限で途中終了しました。表示も保存もしていません。")
    try:
        parsed = json.loads(model_output)
        reply = parsed["reply"].strip()
        state = parsed["state"]
        if not isinstance(state, dict) or not isinstance(state.get("unknowns"), list):
            raise TypeError("state is missing")
        next_scene = apply_scene_change(scene, user_text, parsed.get("scene_change"))
        memory_value = parsed.get("memory")
        evidence_value = parsed.get("memory_evidence")
        evidence = evidence_value.strip() if isinstance(evidence_value, str) else ""
        memory = memory_value.strip() if isinstance(memory_value, str) else None
        if debug:
            print("[DEBUG: 場面変更候補]", json.dumps(parsed.get("scene_change"), ensure_ascii=False))
            print("[DEBUG: 生成した記憶候補]", repr(memory))
            print("[DEBUG: 記憶の根拠]", repr(evidence))
        if memory and (memory in user_text or not evidence or evidence not in user_text
                       or state["unknowns"] or scene or next_scene):
            memory = None
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        if debug:
            print(f"[DEBUG: 生成終了理由] {result.get('done_reason')}")
            print(f"[DEBUG: Ollama 生出力] {model_output!r}")
        if isinstance(error, json.JSONDecodeError):
            reason = "JSONの文法が壊れています"
        elif isinstance(error, KeyError):
            reason = f"必要な項目 {error.args[0]!r} がありません"
        else:
            reason = "reply または一時状態の形式が違います"
        raise RuntimeError(
            f"モデルの出力を読めませんでした（{reason}、終了理由: {result.get('done_reason', '不明')}）。保存していません。"
        ) from error
    if not reply:
        if debug:
            print(f"[DEBUG: 生成終了理由] {result.get('done_reason')}")
            print(f"[DEBUG: Ollama 生出力] {model_output!r}")
        raise RuntimeError("モデルが空の reply を返しました。保存していません。")
    if debug:
        print(f"[DEBUG: 生成結果] 終了理由={result.get('done_reason')}、生成トークン={result.get('eval_count')}、返答文字数={len(reply)}")
        print("[DEBUG: モデルの一時状態・未検証]", json.dumps(state, ensure_ascii=False))
        print("[DEBUG: 場面の構え]", json.dumps(next_scene, ensure_ascii=False))
        print("[DEBUG: 記憶判断]", "保存候補: " + memory if memory else "保存しない")
    return reply, memory, next_scene


def save_memory(content: str) -> dict:
    """Append only the interpretation, never the original user message."""
    next_id = 1
    if MEMORY_FILE.exists():
        with MEMORY_FILE.open("r", encoding="utf-8") as memories:
            for line in memories:
                try:
                    next_id = max(next_id, int(json.loads(line)["id"]) + 1)
                except (ValueError, KeyError, json.JSONDecodeError):
                    pass

    memory = {
        "id": next_id,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with MEMORY_FILE.open("a", encoding="utf-8") as memories:
        memories.write(json.dumps(memory, ensure_ascii=False) + "\n")
    return memory


def show_memories() -> None:
    """Show saved interpretations without asking the model to invent them."""
    if not MEMORY_FILE.exists():
        print("保存済みの記憶はありません。")
        return
    count = 0
    with MEMORY_FILE.open("r", encoding="utf-8") as memories:
        for line in memories:
            try:
                item = json.loads(line)
                print(f"[{item['id']}] {item['content']}")
                count += 1
            except (KeyError, TypeError, json.JSONDecodeError):
                print("[読めない記憶の行をスキップ]")
    if count == 0:
        print("保存済みの記憶はありません。")


def read_user_text() -> str:
    """Read one turn, or collect multiple lines as one turn with /paste."""
    first_line = input("あなた> ")
    if first_line.strip() != "/paste":
        return first_line.strip()

    print("複数行入力中。最後に /send だけの行を入力して送信。")
    lines = []
    while True:
        line = input("... ")
        if line.strip() in {"/send", "/end"}:
            return "\n".join(lines).strip()
        lines.append(line)


def read_taught_reply() -> str:
    """Let the user write the response they wanted, without using model output."""
    print("望んでいたBreaktailの返答を入力。複数行でもOK。最後に /send だけの行。")
    lines = []
    while True:
        line = input("正解> ")
        if line.strip() == "/send":
            return "\n".join(lines).strip()
        lines.append(line)


def export_reviewed_pairs(pairs: list[dict], destination: Path) -> int:
    """Persist only examples explicitly corrected by the user, never ordinary chat."""
    if not pairs:
        return 0
    with destination.open("a", encoding="utf-8") as target:
        for pair in pairs:
            target.write(json.dumps(pair, ensure_ascii=False) + "\n")
    return len(pairs)


def main() -> None:
    print("Breaktail v0.1 — /exit 終了、/paste 複数行、/style-report 発言観測、/teach 望む返答、/export-training 明示保存、/memories 記憶一覧、/profile 確定プロフィール、/scene 現在の場面、/debug 詳細表示")
    history: list[dict] = []
    style_samples: list[dict] = []  # 生の会話はこの起動中のRAMにだけ置く
    reviewed_pairs: list[dict] = []  # /teach で承認した正解例。終了時に消える
    scene: dict | None = None
    debug = DEBUG_MESSAGES
    while True:
        try:
            user_text = read_user_text()
        except (EOFError, KeyboardInterrupt):
            print("\n終了しました。")
            break
        if user_text == "/exit":
            print("終了しました。")
            break
        if user_text == "/memories":
            show_memories()
            continue
        if user_text == "/style-report":
            try:
                print_style_report(make_style_report(style_samples))
                print(f"この起動中の発言: {len(style_samples)}件、/teachで確認した正解例: {len(reviewed_pairs)}件（RAM上）")
            except (ValueError, RuntimeError) as error:
                print(f"エラー: {error}")
            continue
        if user_text == "/teach":
            if len(history) < 2 or history[-2].get("role") != "user" or history[-1].get("role") != "assistant":
                print("直前にBreaktailの返答がないため、教える対象がありません。")
                continue
            try:
                desired = read_taught_reply()
            except (EOFError, KeyboardInterrupt):
                print("\n今回は登録しませんでした。")
                continue
            if not desired:
                print("空なので登録しませんでした。")
                continue
            reviewed_pairs.append({
                "approved_by_user": True,
                "prompt": [message.copy() for message in history[:-1]],
                "completion": [{"role": "assistant", "content": desired}],
            })
            print(f"正解例をRAMに追加 [{len(reviewed_pairs)}]。ファイル保存・LoRA学習はまだしていません。")
            continue
        if user_text == "/export-training":
            if not reviewed_pairs:
                print("/teach で教えた正解例はまだありません。")
                continue
            print("注意: 学習用ファイルには、正解例の元になった生の会話も保存します。通常の長期記憶とは別です。")
            try:
                confirmation = input("保存するなら『保存する』と入力> ")
            except (EOFError, KeyboardInterrupt):
                print("\n保存しませんでした。")
                continue
            if confirmation != "保存する":
                print("保存しませんでした。")
                continue
            try:
                count = export_reviewed_pairs(reviewed_pairs, TRAINING_FILE)
            except OSError as error:
                print(f"保存に失敗しました: {error}")
                continue
            reviewed_pairs.clear()
            print(f"正解例{count}件を学習用ファイルに保存: {TRAINING_FILE}")
            continue
        if user_text == "/profile":
            try:
                confirmed_profile = load_profile()
                if confirmed_profile:
                    for item in confirmed_profile["items"]:
                        print(f"{item['number']}. {item['label']}: {item['value']}")
                else:
                    print("確定したBreaktailのプロフィールはまだありません。")
            except ProfileStoreError as error:
                print(f"エラー: {error}")
            continue
        if user_text == "/scene":
            if scene:
                print(f"現在の場面: {scene['name']}（あなた: {scene['user_role']}／Breaktail: {scene['assistant_role']}）")
            else:
                print("現在の場面: 未設定")
            continue
        if user_text == "/debug":
            debug = not debug
            print("デバッグ表示: " + ("ON" if debug else "OFF"))
            continue
        if user_text == "/capabilities":
            print("できる: テキスト会話、コードの提案、直近4往復の参照、解釈記憶の保存。")
            print("/memories で旧ユーザー記憶を表示。会話中の14Bへは読み戻していません。")
            print("確定したBreaktail自身の20項目プロフィールは /profile で確認でき、再起動後も会話に渡します。")
            print("できない: 外部検索、任意のファイル操作、裏での作業、前セッションの会話の参照。")
            continue
        if not user_text:
            continue

        if is_remember_request(user_text):
            if is_profile_commit_request(user_text):
                items = extract_recent_profile(history)
                if items is None:
                    reply = "直近の会話に完全な20項目のプロフィールが見つからない。保存できてないから、覚えたとは言えない。"
                else:
                    try:
                        saved_profile = save_verified_profile(items)
                        reply = f"プロフィール{len(saved_profile['items'])}項目を保存して、読み戻しも確認した。次の起動でも使える。"
                    except ProfileStoreError as error:
                        reply = f"保存に失敗した。覚えたとは言えない: {error}"
            else:
                reply = "その内容を確実に保存する処理はまだない。覚えたとは言えない。"
            print(f"Breaktail> {reply}")
            style_samples.append({"user": user_text})
            style_samples = style_samples[-200:]
            history.extend([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ])
            history = history[-MAX_HISTORY_MESSAGES:]
            continue

        try:
            reply, memory_text, next_scene = respond_and_interpret(history, user_text, scene, debug)
            saved = None
            if memory_text:
                saved = save_memory(memory_text)
        except KeyboardInterrupt:
            print("\n生成を中断しました。この入力は保存していません。")
            continue
        except RuntimeError as error:
            print(f"エラー: {error}")
            # 失敗も会話中の出来事。生の入力はRAMにだけ残し、次の発言で
            # 再試行するか話題を変えるかを判断できるようにする。
            history.extend([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": "返答の生成に失敗した。この依頼にはまだ答えていない。"},
            ])
            history = history[-MAX_HISTORY_MESSAGES:]
            continue
        print(f"Breaktail> {reply}")
        style_samples.append({"user": user_text})
        style_samples = style_samples[-200:]
        if saved:
            print(f"記憶に保存 [{saved['id']}]: {saved['content']}")
        scene = next_scene
        history.extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ])
        history = history[-MAX_HISTORY_MESSAGES:]


if __name__ == "__main__":
    main()
