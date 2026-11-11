"""Local browser UI. RAM holds live state; reply inputs/outputs are also logged to disk."""

import ast
import difflib
import hashlib
import json
import os
import re
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import breaktail_v02 as tail
from breaktail_pipeline import PipelineObserver
from breaktail_passive_continuity import new_passive_continuity_state, normalize_passive_continuity_state, prepare_user_turn
from breaktail_paths import DATA_ROOT, ensure_data_root, store_path
from breaktail_review_bridge import handle_review
from breaktail_memory_manager import ProfileStoreError, load_profile
from breaktail_style import make_style_report
from breaktail_agent import Workspace
from breaktail_agent_edit_preview import ReplacementSyntaxError, preview as preview_replacement
from breaktail_file_lock import ExclusiveLock
from breaktail_web_agent import WebAgentService


HOST = "127.0.0.1"
PORT = int(os.environ.get("BREAKTAIL_WEB_PORT", "8765"))
RESTORE_FROM = os.environ.get("BREAKTAIL_WEB_RESTORE_FROM")
STATE_FILE = store_path("state", "web_state.json", "BREAKTAIL_WEB_STATE_FILE")
PAGE = Path(__file__).with_name("breaktail_web.html")
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE = {"history": [], "messages": [], "scene": None, "pending": None, "busy": False,
         "conversation_id": secrets.token_urlsafe(16), "style_samples": [], "debug": False,
         "working_state": tail.new_working_state(), "passive_continuity": new_passive_continuity_state()}
EDIT_LOCK = threading.Lock()
PREPARED_EDITS = {}
AGENT_SERVICE = WebAgentService()


def save_state_snapshot() -> None:
    """Persist stable Web session state atomically for process restart."""
    with LOCK:
        snapshot = {
            "messages": list(STATE["messages"]),
            "scene": STATE["scene"],
            "pending": STATE["pending"],
            "busy": False,
            "conversation_id": STATE["conversation_id"],
            "style_samples": list(STATE["style_samples"]),
            "debug": STATE["debug"],
            "working_state": STATE["working_state"],
            "passive_continuity": STATE["passive_continuity"],
        }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".breaktail-web-state-", suffix=".tmp", dir=STATE_FILE.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_FILE)
        # Readback verification catches a failed/partial persistence path without
        # trusting the in-memory write alone.
        with STATE_FILE.open("r", encoding="utf-8") as stream:
            if not isinstance(json.load(stream), dict):
                raise OSError("web state readback is not an object")
    finally:
        temporary.unlink(missing_ok=True)


def restore_from_file(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        snapshot = json.load(stream)
    restore_snapshot(snapshot)
    return len(STATE["messages"])


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """Never let two Windows processes serve different versions on the same port."""
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def restore_snapshot(snapshot):
    """Restore a validated /api/state payload into this process without writing chat to disk."""
    if not isinstance(snapshot, dict) or snapshot.get("busy"):
        raise ValueError("state snapshot is invalid or the source is busy")
    messages = snapshot.get("messages")
    if not isinstance(messages, list):
        raise ValueError("state snapshot has no message list")
    normalized = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"} or not isinstance(item.get("text"), str):
            raise ValueError("state snapshot contains an invalid message")
        normalized.append(dict(item))
    scene = snapshot.get("scene")
    if scene is not None and not isinstance(scene, dict):
        raise ValueError("state snapshot contains an invalid scene")
    pending = snapshot.get("pending")
    if pending is not None and (not isinstance(pending, dict) or not isinstance(pending.get("id"), str) or not isinstance(pending.get("text"), str)):
        raise ValueError("state snapshot contains an invalid pending extraction")
    conversation_id = snapshot.get("conversation_id")
    if conversation_id is None:
        conversation_id = STATE["conversation_id"]  # compatibility with older loopback snapshots
    if (not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 128
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in conversation_id)):
        raise ValueError("state snapshot contains an invalid conversation_id")
    style_samples = snapshot.get("style_samples", [])
    if (not isinstance(style_samples, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("user"), str) for item in style_samples)):
        raise ValueError("state snapshot contains invalid style samples")
    debug = snapshot.get("debug", False)
    if not isinstance(debug, bool):
        raise ValueError("state snapshot contains an invalid debug setting")
    working_state = tail.normalize_working_state(snapshot.get("working_state"))
    passive_continuity = normalize_passive_continuity_state(snapshot.get("passive_continuity"))
    restored_window = normalized[-tail.MAX_HISTORY_MESSAGES:]
    while restored_window and restored_window[0]["role"] != "user":
        restored_window.pop(0)
    history = []
    for item in restored_window:
        content = item["text"]
        if item["role"] == "assistant" and item.get("complete") is False:
            content += "\n[応答は途中で切れました]"
        history.append({"role": item["role"], "content": content,
                        **({"turn_id": item["turn_id"]} if isinstance(item.get("turn_id"), str) else {})})
    with LOCK:
        STATE.update(history=history, messages=normalized, scene=scene, pending=pending,
                     busy=False, conversation_id=conversation_id, style_samples=style_samples[-200:], debug=debug,
                     working_state=working_state, passive_continuity=passive_continuity)


def restore_from_loopback(source_url):
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("state restoration is restricted to a local HTTP server")
    if parsed.port == PORT:
        raise ValueError("source and destination ports must differ")
    endpoint = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/api/state", "", "", ""))
    with urllib.request.urlopen(endpoint, timeout=15) as response:
        snapshot = json.loads(response.read().decode("utf-8"))
    restore_snapshot(snapshot)
    return len(STATE["messages"])


def memories():
    if not tail.MEMORY_FILE.exists():
        return []
    found = []
    with tail.MEMORY_FILE.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "id" in item and "content" in item:
                    found.append(item)
            except json.JSONDecodeError:
                continue
    return found


def open_workspace(workspace_root):
    if (not isinstance(workspace_root, str) or not workspace_root.strip() or
            not Path(workspace_root).is_absolute() or not re.fullmatch(r"[A-Za-z]:", Path(workspace_root).drive)):
        raise ValueError("作業フォルダーの絶対パスを指定してください")
    return Workspace(workspace_root, create_audit=False)


def read_workspace(workspace_root, tool, path):
    if tool not in ("list_files", "read_file"):
        raise ValueError("読取り専用の操作だけ利用できます")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("作業フォルダー内の相対パスを指定してください")
    workspace = open_workspace(workspace_root)
    observation = workspace.execute(tool, {"path": path})
    return {"tool": tool, "workspace": str(workspace.root), "path": path, "observation": observation}


def preview_workspace_replace(workspace_root, path, old, new):
    """Show a bounded literal replacement and syntax check without touching files."""
    if not isinstance(path, str) or not path.strip() or not isinstance(old, str) or not old:
        raise ValueError("対象ファイルと置換前の文字列を指定してください")
    if not isinstance(new, str):
        raise ValueError("置換後の文字列を指定してください")
    workspace = open_workspace(workspace_root)
    target = workspace.path(path)
    if target.suffix.lower() in {".exe", ".dll", ".sys", ".key", ".pfx", ".pem", ".sqlite", ".db"}:
        raise ValueError("この種類のファイルは編集できません")
    observed = workspace.read(path)
    with target.open("rb") as stream:
        if stream.read(3) == b"\xef\xbb\xbf":
            raise ValueError("UTF-8 BOM付きファイルの編集はこの画面では未対応です")
    before = observed["content"]
    if before.count(old) != 1:
        raise ValueError("置換前の文字列はファイル中にちょうど1回必要です")
    candidate = before.replace(old, new, 1)
    if len(candidate.encode("utf-8")) > 64000:
        raise ValueError("変更後のファイルは64KB以内にしてください")
    try:
        syntax = preview_replacement(path, before, candidate, observed["sha256"])
    except ReplacementSyntaxError as error:
        syntax = error.observation
    if target.suffix.lower() == ".py" and syntax.get("reason") == "original_syntax_invalid":
        try:
            ast.parse(candidate, filename=path)
        except SyntaxError as error:
            syntax = {"checked": False, "source": "replacement_candidate_not_written",
                      "error": type(error).__name__, "error_line": error.lineno,
                      "written": False, "execution_performed": False}
        else:
            syntax = {"checked": True, "kind": "candidate_syntax_only",
                      "execution_performed": False}
    patch = "".join(difflib.unified_diff(before.splitlines(keepends=True),
                                          candidate.splitlines(keepends=True),
                                          fromfile="before/" + path, tofile="preview/" + path))
    return {"workspace": str(workspace.root), "path": path, "source_sha256": observed["sha256"],
            "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            "diff": patch[:8000], "diff_truncated": len(patch) > 8000,
            "syntax": syntax, "written": False}


def prepare_workspace_replace(workspace_root, path, old, new):
    result = preview_workspace_replace(workspace_root, path, old, new)
    if result["syntax"].get("source") == "replacement_candidate_not_written":
        return result
    if result["source_sha256"] == result["candidate_sha256"]:
        raise ValueError("変更内容がありません")
    if result["diff_truncated"]:
        raise ValueError("差分が長すぎるため、この画面からは保存できません")
    identity = secrets.token_urlsafe(32)
    with EDIT_LOCK:
        now = time.monotonic()
        for key in list(PREPARED_EDITS):
            if PREPARED_EDITS[key]["expires"] < now:
                del PREPARED_EDITS[key]
        if len(PREPARED_EDITS) >= 32:
            del PREPARED_EDITS[next(iter(PREPARED_EDITS))]
        PREPARED_EDITS[identity] = {"workspace": result["workspace"], "path": path,
                                    "old": old, "new": new,
                                    "source_sha256": result["source_sha256"],
                                    "candidate_sha256": result["candidate_sha256"],
                                    "expires": now + 600}
    return {**result, "preview_id": identity}


def commit_workspace_replace(preview_id):
    if not isinstance(preview_id, str):
        raise ValueError("変更案を先に確認してください")
    with EDIT_LOCK:
        prepared = PREPARED_EDITS.pop(preview_id, None)
    if prepared is None or prepared["expires"] < time.monotonic():
        raise ValueError("変更案の期限が切れました。もう一度確認してください")
    guard = open_workspace(prepared["workspace"])
    with ExclusiveLock(guard.path(".breaktail-agent/worker.lock", internal=True)):
        workspace = Workspace(prepared["workspace"])
        observed = workspace.read(prepared["path"])
        if observed["sha256"] != prepared["source_sha256"]:
            raise ValueError("確認後にファイルが変わりました。読み直してください")
        candidate = observed["content"].replace(prepared["old"], prepared["new"], 1)
        if (observed["content"].count(prepared["old"]) != 1 or
                hashlib.sha256(candidate.encode("utf-8")).hexdigest() != prepared["candidate_sha256"]):
            raise ValueError("確認した変更案と現在の内容が一致しません")
        receipt = {"schema": 1, "workspace": str(workspace.root), "path": prepared["path"],
                   "source_sha256": observed["sha256"],
                   "candidate_sha256": prepared["candidate_sha256"], "status": "prepared"}
        record = workspace.audit_dir / "web-edit.json"
        record.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        result = workspace.execute("replace_text", {"path": prepared["path"],
                                                     "old": prepared["old"], "new": prepared["new"]})
        if not result.get("written") or result["sha256"] != prepared["candidate_sha256"]:
            raise OSError("変更後のファイルを確認できませんでした")
        receipt["status"] = "applied"
        receipt["backup"] = workspace.changes[str(workspace.path(prepared["path"]))]["backup"]
        temp_record = record.with_suffix(".json.tmp")
        temp_record.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_record, record)
        return {"written": True, "workspace": str(workspace.root), "path": prepared["path"],
                "before_sha256": observed["sha256"], "after_sha256": result["sha256"],
                "run_id": workspace.run_id, "backup": receipt["backup"]}


def undo_workspace_edit(workspace_root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("有効な作業IDを指定してください")
    guard = open_workspace(workspace_root)
    with ExclusiveLock(guard.path(".breaktail-agent/worker.lock", internal=True)):
        record = guard.path(f".breaktail-agent/{run_id}/web-edit.json", internal=True)
        if not record.is_file() or record.stat().st_size > 4096:
            raise ValueError("変更記録が見つかりません")
        receipt = json.loads(record.read_text(encoding="utf-8"))
        expected_backup = Path(".breaktail-agent") / run_id / "before-0"
        if (not isinstance(receipt, dict) or receipt.get("schema") != 1 or
                receipt.get("workspace") != str(guard.root) or receipt.get("status") not in ("prepared", "applied") or
                not all(isinstance(receipt.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", receipt[key])
                        for key in ("source_sha256", "candidate_sha256")) or
                (receipt.get("status") == "applied" and
                 (not isinstance(receipt.get("backup"), str) or
                  Path(receipt["backup"]).parts != expected_backup.parts)) or
                (receipt.get("status") == "prepared" and receipt.get("backup") is not None)):
            raise ValueError("変更記録を確認できません")
        target = guard.path(receipt.get("path"))
        backup = guard.path(str(expected_backup), internal=True)
        if not target.is_file() or not backup.is_file() or backup.stat().st_size > 64000:
            raise ValueError("対象またはバックアップが見つかりません")
        original = backup.read_bytes()
        current = target.read_bytes()
        if (hashlib.sha256(original).hexdigest() != receipt["source_sha256"] or
                hashlib.sha256(current).hexdigest() != receipt["candidate_sha256"]):
            raise ValueError("保存後にファイルまたはバックアップが変わりました。上書きしません")
        temporary = target.with_name(target.name + "." + secrets.token_hex(8) + ".undo.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        if hashlib.sha256(target.read_bytes()).hexdigest() != receipt["source_sha256"]:
            raise OSError("取消後の読み戻しに失敗しました")
        receipt["status"] = "undone"
        temporary_record = record.with_name("web-edit." + secrets.token_hex(8) + ".tmp")
        try:
            temporary_record.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary_record, record)
        finally:
            temporary_record.unlink(missing_ok=True)
        return {"undone": True, "workspace": str(guard.root), "path": receipt["path"],
                "sha256": receipt["source_sha256"], "run_id": run_id}


def local_request_allowed(host, origin=None):
    allowed_hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    return host in allowed_hosts and (not origin or origin in {f"http://{name}" for name in allowed_hosts})


def prepare_turn(history, user_text, scene, trace=None, working_state=None, passive_continuity=None):
    """Use the same core turn pipeline as CLI."""
    with LOCK:
        debug = STATE["debug"]
    return tail.prepare_turn(history, user_text, scene, debug=debug, trace=trace,
                             working_state=working_state, passive_continuity=passive_continuity)


def _style_report_text(samples):
    report = make_style_report(samples)
    def lines(items):
        return "\n".join(f"  [{item['number']}] {item['quote']}" for item in items) or "  この範囲では見つからない"
    direct = report["direct_answer_requests"]
    direct_text = ("\nこの会話で明示された返答への要求: 質問の対象に具体的に答えること\n  根拠: "
                   + " / ".join(f"[{item['number']}] {item['quote']}" for item in direct)) if direct else ""
    return ("発言観測レポート（このWeb会話・未学習）\n"
            f"対象: {report['scope']}、ユーザー発言 {report['sample_count']}件\n"
            f"質問らしい発言:\n{lines(report['questions'])}{direct_text}\n"
            f"明示的な訂正・要求:\n{lines(report['corrections'])}\n"
            f"判断しないこと: {report['limit']}\n"
            "これは発言の観測であって、Breaktailが学習した結果ではありません。")


def web_command_reply(user_text, history, scene, conversation_id, style_samples, working_state=None):
    """Expose the established CLI operational commands through the Web chat route.

    Returns None for ordinary conversation.  Command effects stay in the same
    canonical stores used by CLI; no Web-only mirror is introduced.
    """
    if user_text.startswith('/persona '):
        if working_state is None:
            return '人格の切替には現在の会話状態が必要です。',scene
        from breaktail_character import select
        try:
            select(working_state,user_text[len('/persona '):].strip())
        except ValueError:
            return '使い方: /persona atashi または /persona off',scene
        return ('あたし版の会話人格に切り替えた。' if user_text.endswith('atashi') else '会話人格の指定を解除した。'),scene
    if user_text == "/memories" or (re.search(r"記憶", user_text) and
            re.search(r"すべて|全部|全件|一覧", user_text) and
            re.search(r"見せ|表示|一覧|教え", user_text) and
            not re.search(r"消し|削除|忘れ", user_text)):
        rows = memories()
        return ("保存済みの解釈記憶はありません。" if not rows else f"保存済みの解釈記憶 {len(rows)} 件（Raw会話・プロフィールは別管理）:\n" + "\n".join(
            f"[{item['id']}] [未確認の解釈] {item['content']}" for item in rows)), scene
    if user_text.startswith("/forget"):
        argument = user_text[len("/forget"):].strip()
        if not argument.isdigit():
            return "使い方: /forget 番号（番号は /memories で確認）", scene
        try:
            backup = tail.forget_memory(int(argument))
        except (OSError, ValueError) as error:
            return f"削除に失敗しました: {error}", scene
        return (f"記憶 [{argument}] を削除しました。復元用: {backup}" if backup else
                f"記憶 [{argument}] は見つかりません。"), scene
    if user_text == "/profile":
        try:
            profile = load_profile()
        except ProfileStoreError as error:
            return f"エラー: {error}", scene
        return ("確定したBreaktailのプロフィールはまだありません。" if not profile else "\n".join(
            f"{item['number']}. {item['label']}: {item['value']}" for item in profile["items"])), scene
    if user_text == "/scene":
        return (f"現在の場面: {scene['name']}（あなた: {scene['user_role']}／Breaktail: {scene['assistant_role']}）"
                if scene else "現在の場面: 未設定"), scene
    if user_text == "/capabilities":
        return ("できる: テキスト会話、コードの提案、直近16往復の参照、解釈記憶の保存・検索・Memory Gateでの採用と /forget での削除。\n"
                "/memories で記憶を表示。会話では出典Rawを解決でき、Gateを通過した候補だけ14Bへ渡す。\n"
                "確定したBreaktail自身の20項目プロフィールは /profile で確認でき、再起動後も会話に渡す。\n"
                "Web画面の明示操作では、指定した作業フォルダーの一覧・テキスト読取り・差分確認後の文字列置換と取消、作業エージェントの実行・停止・未完了からの再開・実行後の差分確認ができる。会話から自動でファイルを操作する機能はない。\n"
                "できない: 外部検索、Web作業でのコードやテストの実行、裏での作業、前セッションの会話の参照。"), scene
    if user_text == "/debug":
        with LOCK:
            STATE["debug"] = not STATE["debug"]
            enabled = STATE["debug"]
        return "デバッグ表示: " + ("ON（サーバー起動画面に出力）" if enabled else "OFF"), scene
    if user_text == "/style-report":
        try:
            return _style_report_text(style_samples), scene
        except ValueError as error:
            return f"エラー: {error}", scene
    if user_text == "/teach":
        return "使い方: /teach 望んでいたBreaktailの返答。直前のRaw保存済み返答に対してのみ登録する。", scene
    if user_text.startswith("/teach "):
        target = user_text[len("/teach "):].strip()
        if not target:
            return "正解例が空なので登録しませんでした。", scene
        if not tail.can_teach_last_turn(history, raw_saved=True):
            return "直前にRaw保存済みのBreaktail返答がないため、教える対象がありません。", scene
        try:
            result = tail.teacher_store.add_teach(conversation_id, history[-1]["turn_id"],
                                                   [message.copy() for message in history[:-1]], target)
        except tail.teacher_store.TeacherStoreError as error:
            return f"Teacher Storeへの登録を拒否しました: {error}", scene
        return (f"正解例をTeacher Storeへ明示承認として保存 [{result['teacher_id']}]。LoRA学習はまだしていません。"
                if result["inserted"] else f"同じ正解例は既にTeacher Storeにあります [{result['duplicate_of']}]。"), scene
    if user_text == "/export-training":
        return "学習用ファイルには、正解例の元になった生の会話も保存します。出力するなら /export-training 保存する と入力してください。", scene
    if user_text == "/export-training 保存する":
        try:
            count = tail.teacher_store.export_training(tail.TRAINING_FILE)
        except (OSError, tail.teacher_store.TeacherStoreError) as error:
            return f"保存に失敗しました: {error}", scene
        return f"Teacher Storeの有効な正解例{count}件を学習用ファイルに出力: {tail.TRAINING_FILE}", scene
    return None


def web_profile_commit_reply(user_text, history, scene):
    """Match CLI's explicit profile-commit shortcut before model generation."""
    if not tail.is_remember_request(user_text):
        return None
    if not tail.is_profile_commit_request(user_text):
        return "その内容を確実に保存する処理はまだない。覚えたとは言えない。", scene
    items = tail.extract_recent_profile(history)
    if items is None:
        return "直近の会話に完全な20項目のプロフィールが見つからない。保存できてないから、覚えたとは言えない。", scene
    try:
        saved = tail.save_verified_profile(items)
    except ProfileStoreError as error:
        return f"保存に失敗した。覚えたとは言えない: {error}", scene
    return f"プロフィール{len(saved['items'])}項目を保存して、読み戻しも確認した。次の起動でも使える。", scene


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("[web] " + format % args, flush=True)

    def send(self, status, data, kind="application/json; charset=utf-8"):
        content = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not local_request_allowed(self.headers.get("Host")):
            return self.send(403, {"error": "ローカル画面からのみ利用できます"})
        if handle_review(self):
            return
        if self.path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__BREAKTAIL_TOKEN__", TOKEN)
            return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/state":
            with LOCK:
                snapshot = {"messages": list(STATE["messages"]), "scene": STATE["scene"], "pending": STATE["pending"], "busy": STATE["busy"], "conversation_id": STATE["conversation_id"], "debug": STATE["debug"]}
            with tail.TURN_LOG_LOCK:
                snapshot["data_root"] = str(DATA_ROOT.resolve())
                snapshot["state_file"] = str(STATE_FILE.resolve())
                snapshot["turn_logging"] = {
                    "pid": os.getpid(),
                    "file": str(tail.TURN_LOG_FILE.resolve()),
                    "full_trace_file": str(tail.FULL_TRACE_FILE.resolve()),
                    "enabled": True,
                    **tail.TURN_LOG_STATUS,
                }
                snapshot["raw_conversation"] = {"file": str(tail.raw_conversation.RAW_CONVERSATION_FILE.resolve()),
                                                **tail.raw_conversation.RAW_CONVERSATION_STATUS}
            try:
                snapshot["memories"] = memories()
            except OSError:
                snapshot["memories"] = []
            return self.send(200, snapshot)
        self.send(404, {"error": "見つかりません"})

    def do_POST(self):
        if not local_request_allowed(self.headers.get("Host"), self.headers.get("Origin")):
            return self.send(403, {"error": "ローカル画面からのみ利用できます"})
        if handle_review(self):
            return
        if self.headers.get("X-Breaktail-Token") != TOKEN:
            return self.send(403, {"error": "この画面から操作してください"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send(415, {"error": "JSONが必要です"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 20000:
                return self.send(413, {"error": "入力が長すぎます"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self.send(400, {"error": "入力を読めませんでした"})

        if self.path == "/api/reply":
            return self.reply(body)
        if self.path == "/api/workspace/read":
            try:
                result = read_workspace(body.get("workspace"), body.get("tool"), body.get("path"))
            except (ValueError, OSError, UnicodeError) as error:
                return self.send(400, {"error": str(error)})
            return self.send(200, result)
        if self.path == "/api/workspace/preview":
            try:
                result = prepare_workspace_replace(body.get("workspace"), body.get("path"),
                                                   body.get("old"), body.get("new"))
            except (ValueError, OSError, UnicodeError) as error:
                return self.send(400, {"error": str(error)})
            return self.send(200, result)
        if self.path == "/api/workspace/commit":
            try:
                result = commit_workspace_replace(body.get("preview_id"))
            except (ValueError, OSError, UnicodeError, TimeoutError) as error:
                return self.send(409, {"error": str(error)})
            return self.send(200, result)
        if self.path == "/api/workspace/undo":
            try:
                result = undo_workspace_edit(body.get("workspace"), body.get("run_id"))
            except (ValueError, OSError, UnicodeError, TimeoutError, json.JSONDecodeError) as error:
                return self.send(409, {"error": str(error)})
            return self.send(200, result)
        if self.path in ("/api/agent/start", "/api/agent/resume", "/api/agent/status",
                         "/api/agent/cancel", "/api/agent/work", "/api/agent/review"):
            try:
                workspace = str(open_workspace(body.get("workspace")).root)
                if self.path == "/api/agent/start":
                    result = AGENT_SERVICE.start(workspace, body.get("task"))
                elif self.path == "/api/agent/resume":
                    result = AGENT_SERVICE.resume(workspace, body.get("run_id"))
                elif self.path == "/api/agent/status":
                    result = AGENT_SERVICE.status(workspace, body.get("job_id"))
                elif self.path == "/api/agent/cancel":
                    result = AGENT_SERVICE.cancel(workspace, body.get("job_id"))
                elif self.path == "/api/agent/review":
                    result = AGENT_SERVICE.review(workspace, body.get("job_id"))
                else:
                    result = AGENT_SERVICE.work_queued(workspace, body.get("job_id"))
            except (ValueError, OSError, TimeoutError, sqlite3.Error) as error:
                return self.send(409, {"error": str(error)})
            return self.send(200, result)
        if self.path == "/api/extract":
            return self.extract(body)
        if self.path == "/api/clear":
            with LOCK:
                if STATE["busy"]:
                    return self.send(409, {"error": "処理中です"})
                STATE.update(history=[], messages=[], scene=None, pending=None, conversation_id=secrets.token_urlsafe(16),
                             working_state=tail.new_working_state(), passive_continuity=new_passive_continuity_state())
            save_state_snapshot()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "見つかりません"})

    def reply(self, body):
        user_text = body.get("text")
        if not isinstance(user_text, str) or not user_text.strip() or len(user_text) > 10000:
            return self.send(400, {"error": "1万文字以内で入力してください"})
        user_text = user_text.strip()
        with LOCK:
            if STATE["busy"] or STATE["pending"]:
                return self.send(409, {"error": "前の返答を処理中です"})
            STATE["busy"] = True
            history, scene = list(STATE["history"]), STATE["scene"]
            working_state = STATE["working_state"]
            passive_continuity = STATE["passive_continuity"]
            conversation_id = STATE["conversation_id"]
        turn_id = secrets.token_urlsafe(12)
        trace = tail.new_trace(turn_id, conversation_id, channel="web")
        tail.trace_event(trace, "web_turn_started", user_text=user_text, scene_before=scene,
                         history_message_count=len(history))
        with LOCK:
            style_samples = list(STATE["style_samples"])
        command = web_command_reply(user_text, history, scene, conversation_id, style_samples,working_state=working_state)
        if command is None:
            command = web_profile_commit_reply(user_text, history, scene)
        if command is not None:
            # Commands are user utterances too; they update continuity, but never
            # inject a prompt because no model is called on this route.
            _, _, continuity_meta = prepare_user_turn(passive_continuity, user_text, working_state.get("pending"))
            tail.trace_event(trace, "passive_continuity", **continuity_meta)
            tail.trace_component(trace, "passive_continuity", "invoked_empty", "command route has no model prompt", **continuity_meta)
            answer, next_scene = command
            raw_saved = tail.save_raw_turn(trace, user_text, answer, "complete", next_scene)
            observer = PipelineObserver(trace, tail.trace_event)
            observer.record("persistence", "invoked_used" if raw_saved else "error", answer, {"raw_saved": raw_saved},
                            "raw_readback", "command route raw persistence", ["breaktail_raw_conversation"])
            warning = None if raw_saved else "Raw会話を保存できませんでした。"
            with LOCK:
                STATE["scene"] = next_scene
                # Operational commands are visible in the transcript and Raw, but
                # never become conversational evidence or a /teach source turn.
                STATE["messages"].extend([
                    {"role": "user", "text": user_text, "turn_id": turn_id},
                    {"role": "assistant", "text": answer, "complete": True, "turn_id": turn_id},
                ])
                STATE["pending"] = {"id": turn_id, "text": user_text, "memory": None, "warning": warning}
                STATE["busy"] = False
            save_state_snapshot()
            tail.trace_event(trace, "turn_completed", scene_before=scene, scene_after=next_scene,
                             command=user_text.split(maxsplit=1)[0], complete=True, warning=warning)
            observer.record("display", "invoked_used", answer, answer, "web_json", "command reply returned", ["breaktail_web"])
            return self.send(200, {"reply": answer, "complete": True, "turn_id": turn_id, "warning": warning,
                                   "persistence": {"raw_saved": raw_saved, "trace_error": tail.TURN_LOG_STATUS.get("last_error")}})
        try:
            answer, complete, memory, next_scene, warning = prepare_turn(
                history, user_text, scene, trace, working_state, passive_continuity
            )
        except Exception as error:
            tail.trace_event(trace, "turn_error", error_type=type(error).__name__, error=str(error), scene_after=scene)
            tail.save_raw_turn(trace, user_text, "", "failed", scene)
            with LOCK:
                STATE["busy"] = False
            return self.send(502, {"error": str(error)})
        raw_saved = tail.save_raw_turn(trace, user_text, answer, "complete" if complete else "incomplete", next_scene)
        observer = PipelineObserver(trace, tail.trace_event)
        observer.record("persistence", "invoked_used" if raw_saved else "error", answer, {"raw_saved": raw_saved},
                        "raw_readback", "raw turn persistence", ["breaktail_raw_conversation"])
        if not raw_saved:
            warning = (warning + " / " if warning else "") + "Raw会話を保存できませんでした。Memoryは関連付け不能のため保存しませんでした。"
        saved = None
        if memory and raw_saved:
            try:
                saved = tail.save_memory(memory, trace, user_text=user_text)
            except Exception as error:
                tail.trace_event(trace, "memory_save", content=memory, saved_memory_id=None, accepted=False,
                                 rejection_reason=f"save_error:{type(error).__name__}")
                warning = warning or f"記憶の保存に失敗しました: {error}"
        with LOCK:
            STATE["scene"] = next_scene
            STATE["history"] = (history + [
                {"role": "user", "content": user_text, "turn_id": turn_id},
                {"role": "assistant", "content": answer + ("\n[応答は途中で切れました]" if not complete else ""), "turn_id": turn_id},
            ])[-tail.MAX_HISTORY_MESSAGES:]
            STATE["messages"].extend([
                {"role": "user", "text": user_text, "turn_id": turn_id},
                {"role": "assistant", "text": answer, "complete": complete, "turn_id": turn_id},
            ])
            STATE["style_samples"] = (style_samples + [{"user": user_text}])[-200:]
            STATE["pending"] = {"id": turn_id, "text": user_text, "memory": saved, "warning": warning}
            STATE["busy"] = False
        save_state_snapshot()
        tail.trace_event(trace, "turn_completed", scene_before=scene, scene_after=next_scene,
                         saved_memory_id=saved.get("id") if isinstance(saved, dict) else None,
                         complete=complete, warning=warning)
        tail.trace_event(trace, "reply_stage", stage="displayed", text=answer, **tail.stage_metrics(answer),
                         transport="web_json")
        observer.record("display", "invoked_used", answer, answer, "web_json", "reply returned to browser", ["breaktail_web"])
        self.send(200, {"reply": answer, "complete": complete, "turn_id": turn_id, "warning": warning,
                        "persistence": {"raw_saved": raw_saved, "trace_error": tail.TURN_LOG_STATUS.get("last_error")}})

    def extract(self, body):
        with LOCK:
            pending = STATE["pending"]
            if STATE["busy"] or not pending or pending["id"] != body.get("turn_id"):
                return self.send(409, {"error": "処理する発言がありません"})
            STATE["busy"] = True
            saved, warning = pending.get("memory"), pending.get("warning")
        with LOCK:
            STATE["pending"] = None
            STATE["busy"] = False
            next_scene = STATE["scene"]
        save_state_snapshot()
        self.send(200, {"memory": saved, "scene": next_scene, "warning": warning})


if __name__ == "__main__":
    ensure_data_root()
    print(f"Model route: {tail.MODEL}", flush=True)
    print(f"Canonical DATA_ROOT: {DATA_ROOT.resolve()}", flush=True)
    if RESTORE_FROM:
        restored_count = restore_from_loopback(RESTORE_FROM)
        print(f"Restored {restored_count} messages from loopback state in RAM", flush=True)
        save_state_snapshot()
    elif STATE_FILE.exists():
        restored_count = restore_from_file(STATE_FILE)
        print(f"Restored {restored_count} messages from {STATE_FILE.resolve()}", flush=True)
    server = ExclusiveHTTPServer((HOST, PORT), Handler)
    print(f"Turn logging: {tail.TURN_LOG_FILE.resolve()} (PID {os.getpid()})", flush=True)
    print(f"Breaktail web: http://{HOST}:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        save_state_snapshot()
        server.server_close()

