"""Append-only primary-source storage for completed Breaktail conversation turns.

This module deliberately contains no model payloads, retrieval details, extraction
data, or memory decisions.  Those belong only in the Phase 1 diagnostic trace.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from breaktail_paths import store_path
from breaktail_file_lock import ExclusiveLock, process_alive


RAW_CONVERSATION_FILE = store_path("raw", "breaktail_raw_conversations.jsonl", "BREAKTAIL_RAW_CONVERSATION_FILE")
RAW_CONVERSATION_LOCK_FILE = Path(os.environ.get("BREAKTAIL_RAW_CONVERSATION_LOCK_FILE", str(RAW_CONVERSATION_FILE) + ".lock"))
RAW_CONVERSATION_STATUS = {"last_success": None, "last_error": None, "file": str(RAW_CONVERSATION_FILE)}
VALID_STATUSES = {"complete", "incomplete", "failed", "aborted"}


def _warning(error: Exception) -> None:
    RAW_CONVERSATION_STATUS["last_error"] = f"raw:{type(error).__name__}"
    try:
        print(f"[WARNING] Raw会話の保存に失敗 ({type(error).__name__})。会話は続行します。", file=sys.stderr, flush=True)
    except Exception:
        pass


class _FileLock:
    """Keep the existing PID token protocol, recovering only proven dead owners."""

    def _recover_dead_owner(self):
        # Recovery itself needs a crash-safe lock to avoid two reclaimers racing.
        with ExclusiveLock(str(RAW_CONVERSATION_LOCK_FILE) + ".recovery", timeout=0.2):
            try:
                token = RAW_CONVERSATION_LOCK_FILE.read_bytes()
                pid = int(token)
                if process_alive(pid) is False and RAW_CONVERSATION_LOCK_FILE.read_bytes() == token:
                    RAW_CONVERSATION_LOCK_FILE.unlink()
            except (FileNotFoundError, ValueError):
                pass  # Unknown/malformed ownership must not be guessed away.

    def __enter__(self):
        deadline = time.monotonic() + 5
        while True:
            try:
                self.fd = os.open(RAW_CONVERSATION_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                self._recover_dead_owner()
                if time.monotonic() >= deadline:
                    raise TimeoutError("raw conversation store lock timeout")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, traceback):
        try:
            os.close(self.fd)
        finally:
            try:
                RAW_CONVERSATION_LOCK_FILE.unlink()
            except FileNotFoundError:
                pass


def _records() -> list[dict]:
    if not RAW_CONVERSATION_FILE.exists():
        return []
    records = []
    with RAW_CONVERSATION_FILE.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid raw conversation record at line {number}") from error
            if not isinstance(record, dict):
                raise ValueError(f"raw conversation record at line {number} is not an object")
            records.append(record)
    return records


def save_turn(conversation_id: str, turn_id: str, user_text: str, assistant_text: str,
              status: str, timestamp: str | None = None, scene_snapshot: dict | None = None) -> bool:
    """Append one immutable raw turn. Returns False (and warns) if persistence fails.

    `turn_id` is the pre-existing Phase 1 ID. Replaying it is an idempotent no-op.
    """
    try:
        if (not all(isinstance(value, str) and value for value in (conversation_id, turn_id, user_text))
                or not isinstance(assistant_text, str)):
            raise ValueError("raw turn requires non-empty IDs/user text and a string assistant text")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid raw turn status: {status}")
        record = {"conversation_id": conversation_id, "turn_id": turn_id,
                  "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                  "user_text": user_text, "assistant_text": assistant_text, "status": status}
        if scene_snapshot is not None:
            record["scene_snapshot"] = scene_snapshot
        with _FileLock():
            existing = next((item for item in _records() if item.get("turn_id") == turn_id), None)
            if existing is not None:
                stable_fields = ("conversation_id", "turn_id", "user_text", "assistant_text", "status", "scene_snapshot")
                if all(existing.get(field) == record.get(field) for field in stable_fields):
                    return True
                raise ValueError("turn_id already exists with different raw content")
            with RAW_CONVERSATION_FILE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        RAW_CONVERSATION_STATUS.update(last_success=record["timestamp"], last_error=None)
        return True
    except Exception as error:
        _warning(error)
        return False


def get_turn(turn_id: str) -> dict | None:
    """Return the unique raw turn for turn_id, or None when it is absent."""
    for record in _records():
        if record.get("turn_id") == turn_id:
            return record
    return None


def iter_turns(conversation_id: str | None = None):
    """Read primary-source turns without exposing diagnostic trace payloads."""
    for record in _records():
        if conversation_id is None or record.get("conversation_id") == conversation_id:
            yield record


def get_context(conversation_id: str, turn_id: str, before: int = 0, after: int = 0) -> list[dict]:
    """Return the requested local context without crossing conversation boundaries."""
    if before < 0 or after < 0:
        raise ValueError("before and after must be non-negative")
    conversation = [record for record in _records() if record.get("conversation_id") == conversation_id]
    for index, record in enumerate(conversation):
        if record.get("turn_id") == turn_id:
            return conversation[max(0, index - before): index + after + 1]
    return []
