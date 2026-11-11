"""Read-only, bounded pages of Raw turns and separate unverified interpretations."""
import json
from pathlib import Path
from breaktail_memory_hub import ledger_event


PAGE_SIZE = 10
MAX_ROW_CHARS = 128000


def _rows(path, scope):
    found = []
    invalid = 0
    path = Path(path)
    if not path.exists():
        return found, invalid
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if len(line) > MAX_ROW_CHARS:
                invalid += 1
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if not isinstance(row, dict):
                invalid += 1
                continue
            if scope == "raw":
                if not all(isinstance(row.get(key), str) for key in
                           ("conversation_id", "turn_id", "timestamp", "user_text", "assistant_text", "status")):
                    invalid += 1
                    continue
                found.append({"conversation_id": row["conversation_id"], "turn_id": row["turn_id"],
                              "timestamp": row["timestamp"], "status": row["status"],
                              "scene_snapshot": bool(row.get("scene_snapshot")),
                              "messages": [{"speaker": "user", "content": row["user_text"]},
                                           {"speaker": "assistant", "content": row["assistant_text"]}]})
            else:
                if "id" not in row or not isinstance(row.get("content"), str):
                    invalid += 1
                    continue
                found.append({"id": row["id"], "content": row["content"],
                              "created_at": next((row[key] for key in ("recorded_at", "created_at")
                                                  if isinstance(row.get(key), str)), None),
                              "source_turn_ids": [value for value in row.get("source_turn_ids", [])
                                                  if isinstance(value, str) and value] if isinstance(row.get("source_turn_ids", []), list) else [],
                              "verification": "unverified_interpretation"})
    found.reverse()
    return found, invalid


def page_records(memory_path, raw_path, scope, page=1):
    if scope not in ("raw", "interpretations", "ledger"):
        raise ValueError("Raw会話、解釈記憶、確認事項の履歴から選んでください")
    if type(page) is not int or page < 1:
        raise ValueError("ページ番号は1以上の整数にしてください")
    rows, invalid = _rows(raw_path if scope in ("raw", "ledger") else memory_path,
                          "raw" if scope == "ledger" else scope)
    if scope == "ledger":
        events = []
        for row in reversed(rows):
            declaration = ledger_event(row["messages"][0]["content"])
            if declaration and row["status"] == "complete":
                events.append({"conversation_id": row["conversation_id"], "turn_id": row["turn_id"],
                               "timestamp": row["timestamp"], "key": declaration["key"],
                               "label": declaration["label"], "detail": declaration["detail"],
                               "status": declaration["status"], "source": "user_declaration",
                               "externally_verified": False})
        latest = {(event["conversation_id"], event["key"]): event["turn_id"] for event in events}
        for event in events:
            newest = latest[(event["conversation_id"], event["key"])]
            event["is_latest"] = event["turn_id"] == newest
            event["superseded_by_turn_id"] = None if event["is_latest"] else newest
        rows = list(reversed(events))
    elif scope == "interpretations":
        raw_rows, _ = _rows(raw_path, "raw")
        raw_by_id = {row["turn_id"]: row for row in raw_rows}
        for row in rows:
            row["sources"] = []
            for identity in row.pop("source_turn_ids"):
                source = raw_by_id.get(identity)
                row["sources"].append({"turn_id": identity, "raw_found": source is not None,
                                       "timestamp": source["timestamp"] if source else None,
                                       "speaker": "user" if source else None,
                                       "user_text": source["messages"][0]["content"] if source else None})
    total = len(rows)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if page > max(1, pages):
        raise ValueError("ページ範囲を超えています")
    start_index = (page - 1) * PAGE_SIZE
    items = rows[start_index:start_index + PAGE_SIZE]
    return {"scope": scope, "order": "newest_first", "page": page, "page_size": PAGE_SIZE,
            "page_count": pages, "total": total, "start": start_index + 1 if items else 0,
            "end": start_index + len(items), "has_previous": page > 1,
            "has_next": page < pages, "invalid_rows": invalid, "items": items}

