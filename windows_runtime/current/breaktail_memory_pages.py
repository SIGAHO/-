"""Read-only, bounded pages of Raw turns and separate unverified interpretations."""
import json
from pathlib import Path


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
                              "messages": [{"speaker": "user", "content": row["user_text"]},
                                           {"speaker": "assistant", "content": row["assistant_text"]}]})
            else:
                if "id" not in row or not isinstance(row.get("content"), str):
                    invalid += 1
                    continue
                found.append({"id": row["id"], "content": row["content"],
                              "created_at": row.get("created_at") if isinstance(row.get("created_at"), str) else None,
                              "source_turn_id": None, "verification": "unverified_interpretation"})
    found.reverse()
    return found, invalid


def page_records(memory_path, raw_path, scope, page=1):
    if scope not in ("raw", "interpretations"):
        raise ValueError("Raw会話か解釈記憶を選んでください")
    if type(page) is not int or page < 1:
        raise ValueError("ページ番号は1以上の整数にしてください")
    rows, invalid = _rows(raw_path if scope == "raw" else memory_path, scope)
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

