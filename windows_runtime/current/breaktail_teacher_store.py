"""Phase 7.8 canonical Teacher Store.

Only explicit, provenance-backed human corrections can become reply teachers.
Human-authored style material is retained as reference-only material; model output
is always marked synthetic and is never silently promoted.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from breaktail_paths import ensure_data_root, store_path
import breaktail_raw_conversation as raw
from phase8_teacher_policy import blocked_reason, target_hash


SCHEMA_VERSION = "teacher-store/v1"
DB_FILE = store_path("teacher", "teacher_store.sqlite3", "BREAKTAIL_TEACHER_DB")
MODEL_TRACE_FILE = store_path("trace", "breaktail_full_turn_trace.jsonl", "BREAKTAIL_FULL_TRACE_FILE")
VALID_STATUS = {"active", "revoked", "rejected"}
VALID_SOURCE_TYPES = {"human_teacher"}


class TeacherStoreError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(input_context, target_text, source_type):
    return hashlib.sha256(_canonical({"input_context": input_context, "target_text": target_text,
                                      "source_type": source_type}).encode("utf-8")).hexdigest()


def connect(path: Path | None = None):
    ensure_data_root()
    location = Path(path or DB_FILE)
    location.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(location)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS teacher_records (
        teacher_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL,
        source_type TEXT NOT NULL, source_conversation_id TEXT, source_turn_id TEXT,
        input_context TEXT NOT NULL, target_text TEXT NOT NULL, provenance TEXT NOT NULL,
        behavior_tags TEXT NOT NULL, persona_tags TEXT NOT NULL, factual_supervision INTEGER NOT NULL,
        created_at TEXT NOT NULL, approved_at TEXT, status TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE, notes TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS teacher_active_idx ON teacher_records(status, source_type)")
    db.commit()
    return db


def _validate(record):
    source_type = record.get("source_type")
    if source_type not in VALID_SOURCE_TYPES:
        raise TeacherStoreError("unknown source_type")
    if record.get("status", "active") not in VALID_STATUS:
        raise TeacherStoreError("invalid status")
    if not isinstance(record.get("provenance"), dict) or not record["provenance"]:
        raise TeacherStoreError("provenance is required")
    if not isinstance(record.get("input_context"), list):
        raise TeacherStoreError("input_context must be a message list")
    if not isinstance(record.get("target_text"), str):
        raise TeacherStoreError("target_text must be a string")
    if source_type == "human_teacher":
        reason = blocked_reason(record)
        if reason:
            raise TeacherStoreError(reason)
        if not record.get("approved_at"):
            raise TeacherStoreError("human_teacher requires explicit approval")
        if not record.get("source_conversation_id") or not record.get("source_turn_id"):
            raise TeacherStoreError("human_teacher requires source conversation and turn")
        if not record["target_text"].strip():
            raise TeacherStoreError("human_teacher requires target text")
        if target_hash(record["target_text"]) in assistant_target_hashes():
            raise TeacherStoreError("stored assistant output cannot become a teacher, even for another turn")
    if source_type == "synthetic_candidate" and record.get("approved_at"):
        raise TeacherStoreError("synthetic_candidate cannot be promoted by approval")
    if record.get("factual_supervision") and source_type != "human_teacher":
        raise TeacherStoreError("only explicit human_teacher may carry factual supervision")


def add(record: dict, path: Path | None = None):
    record = dict(record)
    record.setdefault("schema_version", SCHEMA_VERSION)
    if record["schema_version"] != SCHEMA_VERSION:
        raise TeacherStoreError("unsupported schema_version")
    record.setdefault("teacher_id", uuid.uuid4().hex)
    record.setdefault("status", "active")
    record.setdefault("created_at", _now())
    record.setdefault("approved_at", None)
    record.setdefault("behavior_tags", [])
    record.setdefault("persona_tags", [])
    record.setdefault("factual_supervision", False)
    record.setdefault("notes", "")
    record["content_hash"] = record.get("content_hash") or content_hash(
        record.get("input_context"), record.get("target_text"), record.get("source_type"))
    _validate(record)
    db = connect(path)
    try:
        prior = db.execute("SELECT teacher_id FROM teacher_records WHERE content_hash=?", (record["content_hash"],)).fetchone()
        if prior:
            return {"inserted": False, "duplicate_of": prior["teacher_id"], "teacher_id": prior["teacher_id"]}
        db.execute("""INSERT INTO teacher_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            record["teacher_id"], record["schema_version"], record["source_type"], record.get("source_conversation_id"),
            record.get("source_turn_id"), _canonical(record["input_context"]), record["target_text"],
            _canonical(record["provenance"]), _canonical(record["behavior_tags"]), _canonical(record["persona_tags"]),
            int(bool(record["factual_supervision"])), record["created_at"], record["approved_at"], record["status"],
            record["content_hash"], record["notes"]))
        db.commit()
    finally:
        db.close()
    return {"inserted": True, "teacher_id": record["teacher_id"]}


def add_teach(conversation_id, turn_id, input_context, target_text, path: Path | None = None):
    source = raw.get_turn(turn_id)
    if not source or source.get("conversation_id") != conversation_id:
        raise TeacherStoreError("Raw source turn is absent")
    if source.get("status") not in {"complete", "incomplete"}:
        raise TeacherStoreError("Raw source turn is not eligible")
    if target_text.strip() == source.get("assistant_text", "").strip():
        raise TeacherStoreError("Existing assistant output is not a human correction")
    return add({"source_type": "human_teacher", "source_conversation_id": conversation_id,
                "source_turn_id": turn_id, "input_context": input_context, "target_text": target_text,
                "provenance": {"kind": "raw_turn", "raw_turn_id": turn_id, "raw_status": source["status"],
                               "target_author": "human", "origin": "explicit_user_correction"},
                "behavior_tags": [], "persona_tags": [], "factual_supervision": False,
                "approved_at": _now(), "notes": "CLI /teach explicit approval"}, path)


def revoke(teacher_id: str, path: Path | None = None):
    db = connect(path)
    try:
        changed = db.execute("UPDATE teacher_records SET status='revoked' WHERE teacher_id=? AND status='active'", (teacher_id,)).rowcount
        db.commit()
    finally:
        db.close()
    return bool(changed)


def assistant_target_hashes():
    """Fail closed on unreadable Raw; normalized copies are still model output."""
    try:
        hashes = {target_hash(row["assistant_text"]) for row in raw.iter_turns()
                  if isinstance(row.get("assistant_text"), str) and row["assistant_text"].strip()}
        # Grounding/postprocess can change the draft. The original generated
        # draft remains in Trace and must not re-enter through a review either.
        if MODEL_TRACE_FILE.exists():
            with MODEL_TRACE_FILE.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    text = None
                    if event.get("event") == "ollama_response":
                        text = event.get("response", {}).get("message", {}).get("content")
                    elif event.get("event") == "reply_stage" and event.get("stage") in {"raw_model", "raw_model_retry", "raw"}:
                        text = event.get("text")
                    if isinstance(text, str) and text.strip():
                        hashes.add(target_hash(text))
        return hashes
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise TeacherStoreError("cannot verify target authorship against Raw") from error


def active_reply_teachers(path: Path | None = None):
    db = connect(path)
    try:
        rows = db.execute("SELECT * FROM teacher_records WHERE status='active' AND source_type='human_teacher' AND approved_at IS NOT NULL ORDER BY created_at").fetchall()
    finally:
        db.close()
    decoded = [{**dict(row), "input_context": json.loads(row["input_context"]), "provenance": json.loads(row["provenance"]),
             "behavior_tags": json.loads(row["behavior_tags"]), "persona_tags": json.loads(row["persona_tags"])} for row in rows]
    blocked_targets = assistant_target_hashes()
    return [row for row in decoded if blocked_reason(row) is None
            and target_hash(row["target_text"]) not in blocked_targets]


def export_training(destination: Path, path: Path | None = None):
    rows = active_reply_teachers(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps({"teacher_id": row["teacher_id"], "schema_version": SCHEMA_VERSION,
                                  "messages": row["input_context"] + [{"role": "assistant", "content": row["target_text"]}],
                                  "behavior_tags": row["behavior_tags"], "persona_tags": row["persona_tags"],
                                  "factual_supervision": bool(row["factual_supervision"]),
                                  "source_group": row["source_conversation_id"], "content_hash": row["content_hash"]}, ensure_ascii=False) + "\n")
    return len(rows)


