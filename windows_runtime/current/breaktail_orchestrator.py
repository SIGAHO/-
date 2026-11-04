"""Durable CLI/daemon wiring for the existing Phase 1/2/3 conversation core.

Only Python's standard library is needed. SQLite is a work journal, NOT a
teacher store. Raw/Trace/Memory retain their existing schemas and paths.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from breaktail_file_lock import ExclusiveLock


DEFAULT_CONFIG = Path(__file__).with_name("orchestrator.json")
STORE_OVERRIDES = (
    "BREAKTAIL_MEMORY_FILE", "BREAKTAIL_TURN_LOG_FILE", "BREAKTAIL_FULL_TRACE_FILE",
    "BREAKTAIL_TRAINING_FILE", "BREAKTAIL_TEACHER_DB", "BREAKTAIL_RAW_CONVERSATION_FILE",
    "BREAKTAIL_RAW_CONVERSATION_LOCK_FILE", "BREAKTAIL_PROFILE_FILE",
)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_config(path=DEFAULT_CONFIG, data_root=None, safe_mode=False):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    defaults = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8-sig"))
    if set(config) - set(defaults):
        raise ValueError("unknown configuration keys: " + ",".join(sorted(set(config) - set(defaults))))
    config = {**defaults, **config}
    if config["schema_version"] != 1 or config["model"] != "qwen2.5:14b":
        raise ValueError("preserve schema 1 and the current BASE model contract")
    for key in ("history_turns", "num_ctx", "max_attempts", "restart_limit", "log_max_bytes", "log_backups"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if not 1 <= config["history_turns"] <= 16 or config["num_ctx"] < 1024:
        raise ValueError("history_turns must be 1..16; num_ctx must be >=1024")
    for key in ("reply_timeout_seconds", "extract_timeout_seconds", "retry_seconds", "poll_seconds",
                "health_interval_seconds", "health_timeout_seconds", "worker_timeout_seconds",
                "restart_backoff_seconds", "minimum_free_bytes"):
        if type(config[key]) not in (int, float) or not 0 < config[key] < float("inf"):
            raise ValueError(f"{key} must be finite and positive")
    if type(config["safe_mode"]) is not bool:
        raise ValueError("safe_mode must be boolean")
    endpoint = urllib.parse.urlparse(config["ollama_url"])
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username:
        raise ValueError("ollama_url must be an HTTP(S) URL without embedded credentials")
    configured_root = data_root or os.environ.get("BREAKTAIL_DATA_ROOT") or config["data_root"]
    root = Path(configured_root).expanduser()
    config["data_root"] = str((root if root.is_absolute() else path.parent / root).resolve())
    config["safe_mode"] = safe_mode or config["safe_mode"]
    return config


def load_core(config):
    """Set paths before imports; never let an inherited per-store path leak data."""
    root = Path(config["data_root"])
    for key in STORE_OVERRIDES:
        if os.environ.get(key) and not Path(os.environ[key]).resolve().is_relative_to(root):
            raise ValueError(f"{key} points outside configured data_root")
    os.environ["BREAKTAIL_DATA_ROOT"] = str(root)
    os.environ["BREAKTAIL_OLLAMA_URL"] = config["ollama_url"]
    os.environ["BREAKTAIL_NUM_CTX"] = str(config["num_ctx"])
    tail = importlib.import_module("breaktail_v02")
    if tail.DATA_ROOT.resolve() != root:
        raise ValueError("core already imported with another data root; use a separate process")
    tail.OLLAMA_URL = config["ollama_url"]
    tail.NUM_CTX = config["num_ctx"]
    tail.MAX_HISTORY_MESSAGES = config["history_turns"] * 2
    tail.REPLY_TIMEOUT_SECONDS = config["reply_timeout_seconds"]
    tail.EXTRACT_TIMEOUT_SECONDS = config["extract_timeout_seconds"]
    tail.ensure_data_root()
    return tail


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".orchestrator-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encode(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise OSError("state readback mismatch")
    finally:
        Path(name).unlink(missing_ok=True)


class Journal:
    def __init__(self, root):
        self.path = Path(root) / "state" / "orchestrator.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL, user_text TEXT NOT NULL, turn_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'queued', phase TEXT NOT NULL DEFAULT 'received',
                attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
                result TEXT, error TEXT, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations(
                request_id TEXT PRIMARY KEY, evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS learning_queue(
                request_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                status TEXT NOT NULL, reasons TEXT NOT NULL, teacher_id TEXT);
        """)
        version = self.get_meta("schema_version")
        if version not in (None, 1):
            self.db.close()
            raise ValueError("unsupported orchestrator journal schema")
        self.meta("schema_version", 1)

    def close(self):
        self.db.close()

    def meta(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, encode(value)))

    def get_meta(self, key):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def submit(self, text, conversation_id="cli", request_id=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("user text is empty")
        if not isinstance(conversation_id, str) or not 0 < len(conversation_id) <= 128:
            raise ValueError("conversation_id must be 1..128 characters")
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 128:
            raise ValueError("request_id must be 1..128 characters")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO requests(id,conversation_id,user_text,turn_id,created_at) VALUES (?,?,?,?,?)",
                            (request_id, conversation_id, text, uuid.uuid4().hex, time.time()))
            row = self.request(request_id)
            if row["conversation_id"] != conversation_id or row["user_text"] != text:
                raise ValueError("request_id already belongs to another input")
        return row

    def request(self, request_id):
        row = self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError("unknown request_id")
        return dict(row)

    def update(self, request_id, **fields):
        allowed = {"status", "phase", "attempts", "available_at", "result", "error"}
        if not fields or set(fields) - allowed:
            raise ValueError("invalid journal update")
        with self.db:
            self.db.execute("UPDATE requests SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                            (*fields.values(), request_id))

    def session(self, conversation_id, core):
        row = self.db.execute("SELECT snapshot FROM sessions WHERE id=?", (conversation_id,)).fetchone()
        if row:
            return json.loads(row[0])
        return {"history": [], "scene": None, "working_state": core.new_working_state(),
                "passive_continuity": core.new_passive_continuity_state()}

    def status(self):
        counts = dict(self.db.execute("SELECT status,COUNT(*) FROM requests GROUP BY status").fetchall())
        return {"schema_version": 1, "requests": counts, "health": self.get_meta("health"),
                "worker": self.get_meta("worker"),
                "supervisor": self.get_meta("supervisor"), "supervisor_failure": self.get_meta("supervisor_failure"),
                "learning_queue": dict(self.db.execute("SELECT status,COUNT(*) FROM learning_queue GROUP BY status").fetchall())}


def make_logger(root, config):
    logger = logging.getLogger("breaktail.orchestrator." + str(Path(root).resolve()))
    if not logger.handlers:
        path = Path(root) / "errors" / "orchestrator.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=config["log_max_bytes"], backupCount=config["log_backups"], encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class Orchestrator:
    def __init__(self, config, core=None):
        self.config = config
        self.root = Path(config["data_root"])
        self.core = core or load_core(config)
        self.debug = False
        self.journal = Journal(self.root)
        self.logger = make_logger(self.root, config)

    def heartbeat(self):
        value = {"pid": os.getpid(), "heartbeat": time.time()}
        self.journal.meta("worker", value)
        self.journal.meta(f"worker:{os.getpid()}", value)

    def publish_status(self):
        atomic_json(self.root / "state" / "orchestrator_status.json", self.journal.status())

    def health(self):
        from breaktail_runtime_facts import fact
        checks = {"journal": self.journal.db.execute("PRAGMA quick_check").fetchone()[0] == "ok",
                  "disk": shutil.disk_usage(self.root).free >= self.config["minimum_free_bytes"],
                  "trace": not bool(self.core.TURN_LOG_STATUS.get("last_error")),
                  "raw": not bool(self.core.raw_conversation.RAW_CONVERSATION_STATUS.get("last_error"))}
        parsed = urllib.parse.urlparse(self.config["ollama_url"])
        url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/api/tags", "", "", ""))
        try:
            with urllib.request.urlopen(url, timeout=self.config["health_timeout_seconds"]) as response:
                models = json.load(response).get("models", [])
            checks["backend"] = any(item.get("name") == self.config["model"] or
                                    item.get("model") == self.config["model"] for item in models)
        except Exception as error:
            checks["backend"] = False
            self.logger.warning("backend health failure: %s", type(error).__name__)
        report = {"at": time.time(), "status": "ok" if all(checks.values()) else "degraded", "checks": checks}
        self.journal.meta("health", report)
        self.core.RUNTIME_FACTS.put(fact("orchestrator.health", report, "orchestrator_healthcheck",
                                         status="ok" if all(checks.values()) else "failed",
                                         ttl_seconds=self.config["health_interval_seconds"] * 2))
        self.publish_status()
        return report

    def _memory_exists(self, turn_id, content):
        if not self.core.MEMORY_FILE.exists():
            return None
        with self.core.MEMORY_FILE.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    if turn_id in row.get("source_turn_ids", []) and row.get("content") == content:
                        return row
        return None

    def _evaluate(self, row, result):
        issues = []
        if not result["complete"]:
            issues.append("generation_incomplete")
        if not result["reply"].strip():
            issues.append("empty_reply")
        if not result.get("raw_saved"):
            issues.append("raw_not_verified")
        if result.get("memory_error"):
            issues.append("memory_not_verified")
        if result.get("warning"):
            issues.append("interpretation_warning")
        if self.core.TURN_LOG_STATUS.get("last_error"):
            issues.append("trace_not_saved")
        health = self.journal.get_meta("health")
        if health and not health["checks"].get("backend"):
            issues.append("backend_unavailable_at_last_check")
        return {"schema_version": 1, "kind": "structural_only", "turn_id": row["turn_id"],
                "conversation_id": row["conversation_id"], "issues": issues,
                "reply_sha256": hashlib.sha256(result["reply"].encode("utf-8")).hexdigest(),
                "semantic_review": "pending", "teacher_eligible": False}

    def process_next(self):
        """One writer for session/model/Raw/Memory; submissions remain concurrent."""
        with ExclusiveLock(self.root / "state" / "orchestrator.worker.lock"):
            self.heartbeat()
            health = self.journal.get_meta("health")
            if not health or time.time() - health["at"] >= self.config["health_interval_seconds"]:
                self.health()
            # Only this lock owner can recover a dead worker's 'running' entry.
            row = self.journal.db.execute("""SELECT * FROM requests r
                WHERE status IN ('queued','running') AND available_at<=?
                AND NOT EXISTS (SELECT 1 FROM requests older
                    WHERE older.conversation_id=r.conversation_id AND older.seq<r.seq
                    AND older.status IN ('queued','running'))
                ORDER BY seq LIMIT 1""", (time.time(),)).fetchone()
            if not row:
                return None
            row = dict(row)
            attempts = row["attempts"] + 1
            self.journal.update(row["id"], status="running", attempts=attempts)
            trace = self.core.new_trace(row["turn_id"], row["conversation_id"], "orchestrator")
            self.core.trace_event(trace, "orchestrator_started", request_id=row["id"], attempt=attempts,
                                  resumed_phase=row["phase"], safe_mode=self.config["safe_mode"])
            try:
                # A crash before the generation checkpoint retries at most max_attempts.
                if attempts > self.config["max_attempts"] and not row["result"]:
                    raise RuntimeError("crash retry budget exhausted")
                result = json.loads(row["result"]) if row["result"] else self._generate(row, trace)
                self._persist(row, result, trace)
            except Exception as error:
                self._failure(row, attempts, trace, error)
            self.heartbeat()
            self.publish_status()
            return self.journal.request(row["id"])

    def _generate(self, row, trace):
        started = time.monotonic()
        before = self.journal.session(row["conversation_id"], self.core)
        snapshot = copy.deepcopy(before)
        # Session state chooses committed IDs; the primary Raw store supplies text.
        # An orphan Raw append from a crash must not be mistaken for a committed turn.
        sources = {item["turn_id"]: item for item in self.core.raw_conversation.iter_turns(row["conversation_id"])}
        history = []
        for item in snapshot["history"][-self.config["history_turns"] * 2:]:
            source = sources.get(item["turn_id"])
            if not source or source.get("status") not in {"complete", "incomplete"}:
                raise ValueError("committed history has no eligible Raw source")
            content = source["user_text"] if item["role"] == "user" else source["assistant_text"]
            if item["role"] == "assistant" and source["status"] == "incomplete":
                content = "[応答は途中で切れました]\n" + content
            history.append({"role": item["role"], "content": content, "turn_id": item["turn_id"]})
        snapshot["history"] = history
        self.core.trace_event(trace, "orchestrator_history", source="committed_session_ids+Raw",
                              history_messages=len(history), history_turns=self.config["history_turns"])
        self.core.PipelineObserver(trace, self.core.trace_event).record(
            "orchestrator_history", "invoked_used" if history else "invoked_empty",
            output_value={"history_messages": len(history)}, decision="restore_committed_raw",
            reason="session IDs select only committed turns", provenance=["Raw", "orchestrator_journal"],
            latency_ms=(time.monotonic() - started) * 1000)
        if row["user_text"].startswith("/"):
            raise ValueError("management commands must use interactive chat or dedicated CLI subcommands")
        shortcut = None
        if self.core.is_remember_request(row["user_text"]):
            if self.config["safe_mode"]:
                shortcut = ("safe modeではプロフィールの確定保存を停止しています。", snapshot["scene"])
            else:
                web = importlib.import_module("breaktail_web")
                shortcut = web.web_profile_commit_reply(row["user_text"], snapshot["history"], snapshot["scene"])
        if shortcut:
            reply, scene = shortcut
            complete, memory, warning = True, None, None
        else:
            reply, complete, memory, scene, warning = self.core.prepare_turn(
                snapshot["history"][-self.config["history_turns"] * 2:], row["user_text"], snapshot["scene"],
                debug=self.debug, trace=trace, working_state=snapshot["working_state"],
                passive_continuity=snapshot["passive_continuity"])
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("empty model reply")
        snapshot["scene"] = scene
        snapshot["history"] = (snapshot["history"] + [
            {"role": "user", "content": row["user_text"], "turn_id": row["turn_id"]},
            {"role": "assistant", "content": reply if complete else "[応答は途中で切れました]\n" + reply,
             "turn_id": row["turn_id"]}])[-self.config["history_turns"] * 2:]
        result = {"reply": reply, "complete": bool(complete), "memory": memory,
                  "warning": warning, "snapshot": snapshot, "raw_saved": False,
                  "memory_saved_id": None, "memory_error": None, "safe_mode": self.config["safe_mode"]}
        self.journal.update(row["id"], phase="generated", result=encode(result))
        return result

    def _persist(self, row, result, trace):
        started = time.monotonic()
        # Replays use the SAME turn_id and SAME draft. Raw.save_turn is idempotent.
        if not self.core.save_raw_turn(trace, row["user_text"], result["reply"],
                                       "complete" if result["complete"] else "incomplete", result["snapshot"]["scene"]):
            raise OSError("Raw persistence/readback failed")
        result["raw_saved"] = True
        self.journal.update(row["id"], phase="raw_saved", result=encode(result))
        if result.get("memory") and not (self.config["safe_mode"] or result.get("safe_mode")):
            try:
                existing = self._memory_exists(row["turn_id"], result["memory"])
                saved = existing or self.core.save_memory(result["memory"], trace, user_text=row["user_text"])
                result["memory_saved_id"] = saved.get("id") if saved else None
            except Exception as error:
                result["memory_error"] = type(error).__name__
                self.core.trace_event(trace, "memory_save", accepted=False, rejection_reason="orchestrator:" + type(error).__name__)
                self.logger.warning("memory failure turn=%s type=%s", row["turn_id"], type(error).__name__)
        evidence = self._evaluate(row, result)
        # Queue contains evidence references ONLY: there is intentionally no target column.
        self.core.RUNTIME_FACTS.start_operation("orchestrator.commit")
        with self.journal.db:
            self.journal.db.execute("INSERT OR REPLACE INTO evaluations VALUES (?,?)", (row["id"], encode(evidence)))
            self.journal.db.execute("INSERT OR IGNORE INTO learning_queue VALUES (?,?,?,?,?,NULL)",
                                    (row["id"], row["turn_id"], row["conversation_id"],
                                     "needs_external_teacher", encode(evidence["issues"] or ["semantic_review_pending"])))
            self.journal.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)",
                                    (row["conversation_id"], encode(result["snapshot"])))
            self.journal.db.execute("UPDATE requests SET status='done',phase='committed',result=?,error=NULL WHERE id=?",
                                    (encode(result), row["id"]))
        verified = (self.journal.request(row["id"])["status"] == "done"
                    and self.journal.session(row["conversation_id"], self.core) == result["snapshot"])
        self.core.RUNTIME_FACTS.finish_operation("orchestrator.commit", executed=True, verified=verified,
            status="ok" if verified else "failed", verification_source="SQLite request/session readback",
            result_summary="session committed; teacher registration remains gated")
        self.core.trace_event(trace, "orchestrator_evaluation", **evidence)
        observer = self.core.PipelineObserver(trace, self.core.trace_event)
        observer.record("persistence", "error" if result["memory_error"] else "invoked_used",
                        output_value={"raw_saved": True, "session_verified": verified,
                                      "memory_saved_id": result["memory_saved_id"]},
                        decision="durable_commit", reason="Raw/Memory readback and SQLite session commit",
                        provenance=["breaktail_raw_conversation", "orchestrator_journal"],
                        latency_ms=(time.monotonic() - started) * 1000)
        observer.record("evaluation", "invoked_used", output_value=evidence,
                        decision="structural_only", reason="semantic quality requires external review",
                        provenance=["orchestrator_evaluation"])
        observer.record("learning_queue", "invoked_used", output_value={"request_id": row["id"], "target_present": False},
                        decision="needs_external_teacher", reason="model outputs never become targets",
                        provenance=["orchestrator_evaluation"])
        self.core.trace_event(trace, "turn_completed", complete=result["complete"],
                              saved_memory_id=result["memory_saved_id"], raw_saved=True,
                              warning=result["warning"], evaluation_kind="structural_only",
                              learning_status="needs_external_teacher")
        self.logger.info("committed turn=%s issues=%s", row["turn_id"], ",".join(evidence["issues"]))

    def _failure(self, row, attempts, trace, error):
        terminal = attempts >= self.config["max_attempts"]
        name = type(error).__name__
        # Last committed session stays intact; do not undo immutable Raw/Trace.
        self.journal.update(row["id"], status="failed" if terminal else "queued", error=name,
                            available_at=time.time() + self.config["retry_seconds"])
        self.core.trace_event(trace, "orchestrator_rollback", scope="uncommitted_session", error_type=name,
                              terminal=terminal, immutable_evidence_retained=True)
        if terminal:
            try:
                if not self.core.raw_conversation.get_turn(row["turn_id"]):
                    self.core.save_raw_turn(trace, row["user_text"], "", "failed", None)
            except Exception as raw_error:
                self.logger.error("failed Raw readback turn=%s type=%s", row["turn_id"], type(raw_error).__name__)
            evidence = {"schema_version": 1, "kind": "structural_only", "turn_id": row["turn_id"],
                        "conversation_id": row["conversation_id"], "issues": ["request_failed", name],
                        "semantic_review": "pending", "teacher_eligible": False}
            with self.journal.db:
                self.journal.db.execute("INSERT OR REPLACE INTO evaluations VALUES (?,?)", (row["id"], encode(evidence)))
                self.journal.db.execute("INSERT OR IGNORE INTO learning_queue VALUES (?,?,?,?,?,NULL)",
                                        (row["id"], row["turn_id"], row["conversation_id"], "needs_external_teacher", encode(evidence["issues"])))
        self.logger.error("request failure turn=%s type=%s terminal=%s", row["turn_id"], name, terminal)

    def review(self, request_id, target, reviewer):
        """Explicit human review, never an automatic model->teacher conversion."""
        if self.config["safe_mode"]:
            raise ValueError("safe mode disables teacher registration")
        if not isinstance(reviewer, str) or not reviewer.strip() or not target.strip():
            raise ValueError("human reviewer and nonempty correction are required")
        from phase8_teacher_policy import target_hash
        row = self.journal.request(request_id)
        if row["status"] != "done":
            raise ValueError("only a completed, persisted turn can receive a teacher")
        # Reject target-model output from ANY turn, including normalized copies.
        if any(target_hash(item.get("assistant_text", "")) == target_hash(target)
               for item in self.core.raw_conversation.iter_turns()):
            raise ValueError("target matches stored assistant output; self-training is forbidden")
        source = self.core.raw_conversation.get_turn(row["turn_id"])
        if not source or source["conversation_id"] != row["conversation_id"]:
            raise ValueError("verified Raw source is required")
        result = json.loads(row["result"])
        context = result["snapshot"]["history"][:-1]
        record = self.core.teacher_store.add({
            "source_type": "human_teacher", "source_conversation_id": row["conversation_id"],
            "source_turn_id": row["turn_id"], "input_context": context, "target_text": target,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "provenance": {"kind": "raw_turn", "raw_turn_id": row["turn_id"], "target_author": "human",
                           "origin": "explicit_cli_review", "reviewer": reviewer},
            "notes": "Explicit reviewed correction; no automatic training or deployment."})
        with self.journal.db:
            self.journal.db.execute("UPDATE learning_queue SET status='reviewed',teacher_id=? WHERE request_id=?",
                                    (record["teacher_id"], request_id))
        return record

    def command(self, text, conversation_id):
        """Retain established interactive CLI commands without sending them to LLM."""
        if not text.startswith("/"):
            return None
        snapshot = self.journal.session(conversation_id, self.core)
        if text == "/debug":
            self.debug = not self.debug
            return "デバッグ表示: " + ("ON" if self.debug else "OFF")
        if text == "/capabilities":
            return (f"直近{self.config['history_turns']}往復、Raw照合した履歴復元、Memory Gate、RuntimeFacts、応答後の保存と評価に対応。"
                    "常駐ワーカーの監視・再起動とレビュー待ちキューも利用可能。外部検索や任意の操作ツールは未接続。")
        if text == "/teach":
            return "使い方: /teach 人が書いた正解の返答。対象モデルの生成文は登録できません。"
        if text.startswith("/teach "):
            last = self.journal.db.execute("SELECT id FROM requests WHERE conversation_id=? AND status='done' ORDER BY seq DESC LIMIT 1",
                                           (conversation_id,)).fetchone()
            if not last:
                return "教える対象となるRaw保存済みの応答がありません。"
            record = self.review(last["id"], text[len("/teach "):], "explicit_cli_user")
            return f"レビュー済み正解例を保存しました: {record['teacher_id']}。モデル学習は実行していません。"
        if self.config["safe_mode"] and (text.startswith("/forget") or text.startswith("/export-training")):
            return "safe modeではMemory削除と学習用出力を停止しています。"
        # Reuse the existing command adapter; importing it does not start a server.
        web = importlib.import_module("breaktail_web")
        reply = web.web_command_reply(text, snapshot["history"], snapshot["scene"], conversation_id,
                                      [{"user": item["content"]} for item in snapshot["history"] if item["role"] == "user"])
        return reply[0] if reply else "未対応のコマンドです。/memories /profile /scene /capabilities /teach /exit が使えます。"


def worker_loop(engine, once=False):
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    next_health = 0
    try:
        while not stopped:
            engine.heartbeat()
            if time.monotonic() >= next_health:
                engine.health()
                next_health = time.monotonic() + engine.config["health_interval_seconds"]
            engine.process_next()
            if once:
                break
            time.sleep(engine.config["poll_seconds"])
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def supervise(config, config_path, once=False):
    """Restart ONLY our child. Never stop an existing Ollama/Web/Studio process."""
    root = Path(config["data_root"])
    journal = Journal(root)
    logger = make_logger(root, config)
    stopped = False
    child = None
    def stop(*_):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with ExclusiveLock(root / "state" / "orchestrator.supervisor.lock", timeout=0):
            journal.meta("supervisor_failure", None)
            for restart in range(config["restart_limit"] + 1):
                if stopped:
                    break
                command = [sys.executable, str(Path(__file__).resolve()), "--config", str(Path(config_path).resolve()),
                           "--data-root", str(root)]
                if config["safe_mode"]:
                    command.append("--safe-mode")
                command.append("worker")
                if once:
                    command.append("--once")
                started = time.time()
                journal.meta("worker", {"pid": None, "heartbeat": started})
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                journal.meta("supervisor", {"pid": os.getpid(), "child_pid": child.pid, "restarts": restart})
                while child.poll() is None and not stopped:
                    worker = journal.get_meta(f"worker:{child.pid}") or {}
                    heartbeat = worker.get("heartbeat", started) if worker.get("pid") == child.pid else started
                    if time.time() - heartbeat > config["worker_timeout_seconds"]:
                        logger.error("owned worker watchdog expired pid=%s", child.pid)
                        child.kill()
                        break
                    time.sleep(min(1, config["poll_seconds"]))
                if stopped:
                    break
                child.wait()
                if child.returncode == 0:
                    return 0
                logger.error("owned worker exited pid=%s code=%s restart=%s", child.pid, child.returncode, restart)
                if restart < config["restart_limit"]:
                    deadline = time.monotonic() + config["restart_backoff_seconds"] * (restart + 1)
                    while not stopped and time.monotonic() < deadline:
                        time.sleep(0.1)
            if not stopped:
                journal.meta("supervisor_failure", {"at": time.time(), "reason": "restart_budget_exhausted"})
                return 1
            return 0
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
        journal.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def public_result(row):
    value = json.loads(row["result"]) if row.get("result") else {}
    return {"request_id": row["id"], "turn_id": row["turn_id"], "conversation_id": row["conversation_id"],
            "status": row["status"], "error": row["error"],
            **{key: value.get(key) for key in ("reply", "complete", "raw_saved", "memory_saved_id", "memory_error", "warning")}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="read config and show wiring; no model calls or writes")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("chat", "submit"):
        entry = sub.add_parser(name)
        entry.add_argument("--text")
        entry.add_argument("--conversation-id", default="cli")
        entry.add_argument("--request-id")
    for name in ("run", "worker", "daemon"):
        sub.add_parser(name).add_argument("--once", action="store_true")
    sub.add_parser("health")
    sub.add_parser("queue").add_argument("--limit", type=int, default=20)
    status = sub.add_parser("status")
    status.add_argument("--request-id")
    review = sub.add_parser("review")
    review.add_argument("--request-id", required=True)
    review.add_argument("--target-file", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    sub.add_parser("export-training")
    args = parser.parse_args(argv)
    engine = None
    try:
        config = load_config(args.config, args.data_root, args.safe_mode)
        if args.dry_run:
            print(encode({"dry_run": True, "config": config, "command": args.command,
                          "pipeline": ["journal", "restore_history", "prepare_turn:MemoryGate/RuntimeFacts/Grounding/postprocess",
                                       "Raw_readback", "Memory_v2_readback", "session_commit", "structural_evaluation", "review_queue"],
                          "teacher_policy": "reviewed external/human path only; never recycle target-model outputs"}))
            return 0
        if args.command == "daemon":
            return supervise(config, args.config, args.once)
        engine = Orchestrator(config)
        if args.command == "health":
            report = engine.health()
            print(encode(report))
            return 0 if report["status"] == "ok" else 1
        if args.command == "status":
            print(encode(public_result(engine.journal.request(args.request_id)) if args.request_id else engine.journal.status()))
        elif args.command == "queue":
            if not 1 <= args.limit <= 1000:
                raise ValueError("queue limit must be 1..1000")
            rows = engine.journal.db.execute("SELECT * FROM learning_queue ORDER BY rowid DESC LIMIT ?", (args.limit,)).fetchall()
            print(encode([{**dict(row), "reasons": json.loads(row["reasons"])} for row in rows]))
        elif args.command == "submit":
            text = args.text if args.text is not None else sys.stdin.read()
            print(encode(public_result(engine.journal.submit(text, args.conversation_id, args.request_id))))
        elif args.command in {"run", "worker"}:
            worker_loop(engine, args.once)
        elif args.command == "review":
            print(encode(engine.review(args.request_id, args.target_file.read_text(encoding="utf-8-sig"), args.reviewer)))
        elif args.command == "export-training":
            if config["safe_mode"]:
                raise ValueError("safe mode disables training export")
            with ExclusiveLock(engine.root / "state" / "orchestrator.worker.lock"):
                count = engine.core.teacher_store.export_training(engine.core.TRAINING_FILE)
            print(encode({"reviewed_teachers": count, "file": str(engine.core.TRAINING_FILE), "training_executed": False}))
        elif args.command == "chat":
            while True:
                try:
                    text = args.text if args.text is not None else engine.core.read_user_text()
                except (EOFError, KeyboardInterrupt):
                    break
                if text.strip() == "/exit":
                    break
                if not text.strip():
                    continue
                try:
                    with ExclusiveLock(engine.root / "state" / "orchestrator.worker.lock"):
                        command_reply = engine.command(text, args.conversation_id)
                except (ValueError, OSError) as error:
                    print(encode({"command_error": str(error)}))
                    if args.text is not None:
                        return 1
                    continue
                if command_reply is not None:
                    print(encode({"command_reply": command_reply}) if args.text is not None else command_reply)
                    if args.text is not None:
                        return 0
                    continue
                row = engine.journal.submit(text, args.conversation_id, args.request_id)
                while row["status"] not in {"done", "failed"}:
                    engine.process_next()
                    row = engine.journal.request(row["id"])
                    if row["status"] not in {"done", "failed"}:
                        time.sleep(config["poll_seconds"])
                print(encode(public_result(row)) if args.text is not None else "Breaktail> " +
                      (json.loads(row["result"])["reply"] if row["status"] == "done" else "処理失敗。ログと状態を保存しました。"))
                if args.text is not None:
                    return 0 if row["status"] == "done" else 1
        return 0
    except (ValueError, OSError, sqlite3.Error, TimeoutError) as error:
        print(encode({"error": type(error).__name__, "detail": str(error)}), file=sys.stderr)
        return 1
    finally:
        if engine:
            engine.journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
