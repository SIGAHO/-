"""Explicit, append-only links between two user Raw turns; no inferred confirmation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from breaktail_file_lock import ExclusiveLock
from breaktail_memory_hub import normalized
from breaktail_memory_pages import _rows


def _label(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 80 or "\n" in value:
        raise ValueError("訂正する話題を2–80文字で指定してください")
    return value.strip()


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise ValueError("Rawの出典IDを指定してください")
    return value


def _source_digest(row):
    fields = {key: row[key] for key in ("conversation_id", "turn_id", "timestamp", "status")}
    fields["user_text"] = row["messages"][0]["content"]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _raw_digest(row):
    fields = {key: row[key] for key in ("conversation_id", "turn_id", "timestamp", "status", "user_text")}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _source_pair(raw_path, old_turn_id, new_turn_id):
    old_turn_id, new_turn_id = _identity(old_turn_id), _identity(new_turn_id)
    if old_turn_id == new_turn_id:
        raise ValueError("訂正前後に異なる出典IDを指定してください")
    rows, invalid = _rows(raw_path, "raw")
    if invalid:
        raise ValueError("Raw会話に読取れない行があり、訂正を登録できません")
    chronological = list(reversed(rows))
    matches = {identity: [(index, row) for index, row in enumerate(chronological)
                          if row["turn_id"] == identity]
               for identity in (old_turn_id, new_turn_id)}
    if any(len(found) != 1 for found in matches.values()):
        raise ValueError("出典IDをRaw会話で一意に確認できません")
    old_index, old = matches[old_turn_id][0]
    new_index, new = matches[new_turn_id][0]
    if (old_index >= new_index or old["conversation_id"] != new["conversation_id"] or
            old["status"] != "complete" or new["status"] != "complete"):
        raise ValueError("同じ会話の完了した発言を古い順に指定してください")
    return old, new


def preview(raw_path, label, old_turn_id, new_turn_id):
    label = _label(label)
    old, new = _source_pair(raw_path, old_turn_id, new_turn_id)
    return {"label": label, "key": normalized(label), "conversation_id": old["conversation_id"],
            "old": {"turn_id": old["turn_id"], "timestamp": old["timestamp"],
                    "speaker": "user", "text": old["messages"][0]["content"], "sha256": _source_digest(old)},
            "new": {"turn_id": new["turn_id"], "timestamp": new["timestamp"],
                    "speaker": "user", "text": new["messages"][0]["content"], "sha256": _source_digest(new)},
            "external_verification": False, "written": False}


def _records(path):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if (not isinstance(record, dict) or record.get("schema") != 1 or
                    not all(isinstance(record.get(key), str) for key in
                            ("id", "key", "label", "conversation_id", "old_turn_id", "new_turn_id", "created_at"))):
                raise ValueError("訂正履歴が破損しています。追記しません")
            records.append(record)
    return records


def history(raw_path, ledger_path, label, anchor_turn_id):
    label = _label(label)
    anchor_turn_id = _identity(anchor_turn_id)
    rows, invalid = _rows(raw_path, "raw")
    if invalid:
        raise ValueError("Raw会話に読取れない行があります")
    anchors = [row for row in rows if row["turn_id"] == anchor_turn_id]
    if len(anchors) != 1:
        raise ValueError("出典IDをRaw会話で一意に確認できません")
    conversation_id = anchors[0]["conversation_id"]
    sources = {}
    duplicates = set()
    for row in rows:
        if row["turn_id"] in sources:
            duplicates.add(row["turn_id"])
        sources[row["turn_id"]] = row
    records = [record for record in _records(ledger_path)
               if record["conversation_id"] == conversation_id and record["key"] == normalized(label)]
    items = []
    for record in records:
        old, new = sources.get(record["old_turn_id"]), sources.get(record["new_turn_id"])
        verified = bool(old and new and record["old_turn_id"] not in duplicates
                        and record["new_turn_id"] not in duplicates
                        and record.get("old_source_sha256") == _source_digest(old)
                        and record.get("new_source_sha256") == _source_digest(new))
        items.append({**record, "old_text": old["messages"][0]["content"] if verified else None,
                      "new_text": new["messages"][0]["content"] if verified else None,
                      "sources_available": verified, "external_verification": False})
    return {"label": label, "conversation_id": conversation_id, "count": len(items),
            "latest_turn_id": items[-1]["new_turn_id"] if items and items[-1]["sources_available"] else None,
            "latest_text": items[-1]["new_text"] if items and items[-1]["sources_available"] else None,
            "items": items}


def commit(raw_path, ledger_path, label, old_turn_id, new_turn_id, expected_old_sha256, expected_new_sha256):
    if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (expected_old_sha256, expected_new_sha256)):
        raise ValueError("確認した出典ハッシュを指定してください")
    ledger_path = Path(ledger_path)
    with ExclusiveLock(ledger_path.with_suffix(ledger_path.suffix + ".lock")):
        checked = preview(raw_path, label, old_turn_id, new_turn_id)
        if (checked["old"]["sha256"] != expected_old_sha256 or
                checked["new"]["sha256"] != expected_new_sha256):
            raise ValueError("確認後にRawの出典が変わりました。登録しません")
        existing = [record for record in _records(ledger_path)
                    if record["conversation_id"] == checked["conversation_id"] and record["key"] == checked["key"]]
        if existing and (existing[-1]["old_turn_id"], existing[-1]["new_turn_id"]) == (old_turn_id, new_turn_id):
            return {"record": existing[-1], "already_recorded": True}
        if existing and existing[-1]["new_turn_id"] != old_turn_id:
            raise ValueError("この話題の最新出典から続けてください")
        record = {"schema": 1, "id": uuid.uuid4().hex, "conversation_id": checked["conversation_id"],
                  "key": checked["key"], "label": checked["label"], "old_turn_id": old_turn_id,
                  "new_turn_id": new_turn_id, "created_at": datetime.now(timezone.utc).isoformat(),
                  "old_source_sha256": checked["old"]["sha256"],
                  "new_source_sha256": checked["new"]["sha256"],
                  "source": "explicit_user_selection", "external_verification": False}
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {"record": record, "already_recorded": False}


def match_for_question(raw_path, ledger_path, query, conversation_id, source_rows):
    """Return one exact, intact correction chain for a narrow current-state question.

    The caller supplies its already filtered Raw rows. Missing/truncated sources,
    altered Raw, another matching topic, or a later unlinked correction all decline.
    """
    if not (isinstance(query, str) and len(query) <= 160 and not re.search(r'[\n「」『』]', query)
            and re.search(r"訂正|最新|今は|現在|どっち|どれ", query)
            and re.search(r"[？?]|教え|何|どっち|どれ|どう|どこ", query)):
        return None
    records = [r for r in _records(ledger_path)
               if r["conversation_id"] == conversation_id and r["key"] in normalized(query)]
    if not records:
        return None
    keys = {r["key"] for r in records}
    if len(keys) != 1:
        return None
    latest = records[-1]
    if (len(query) > len(latest["label"]) + 35 or
            re.search(r'[。、;；]|それと|ついで|加えて|他にも', query)):
        return None
    chain = history(raw_path, ledger_path, latest["label"], records[0]["old_turn_id"])
    if (chain["conversation_id"] != conversation_id or len(chain["items"]) != len(records)
            or not all(item["sources_available"] for item in chain["items"])
            or any(before["new_turn_id"] != after["old_turn_id"]
                   for before, after in zip(chain["items"], chain["items"][1:]))):
        return None
    by_id = {r["turn_id"]: (index, r) for index, r in enumerate(source_rows)}
    old_found, new_found = by_id.get(latest["old_turn_id"]), by_id.get(latest["new_turn_id"])
    if not old_found or not new_found or old_found[0] >= new_found[0]:
        return None
    old, new = old_found[1], new_found[1]
    if (old["conversation_id"] != conversation_id or new["conversation_id"] != conversation_id or
            len(old["user_text"]) > 400 or len(new["user_text"]) > 400 or
            latest.get("old_source_sha256") != _raw_digest(old) or
            latest.get("new_source_sha256") != _raw_digest(new)):
        return None
    if any(latest["key"] in normalized(r["user_text"]) for r in source_rows[new_found[0]+1:]):
        return None
    return {"label": latest["label"], "old_turn_id": old["turn_id"],
            "new_turn_id": new["turn_id"], "old_text": old["user_text"],
            "new_text": new["user_text"], "old_timestamp": old["timestamp"],
            "new_timestamp": new["timestamp"], "source": "explicit_user_selection",
            "external_verification": False}

