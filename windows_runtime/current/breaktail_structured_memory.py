"""Phase 3 schema, validation, and conservative temporal normalization.

This module does not read Raw conversations.  Callers supply an already-issued
turn ID; Phase 4 may add read-side linkage separately.
"""

from datetime import datetime, timedelta


MEMORY_TYPES = {"episode", "state", "plan", "preference", "fact"}
TIME_PRECISIONS = {"minute", "hour", "day", "month", "season", "year", "range", "unknown"}
STATUS = "unverified_interpretation"


class MemoryValidationError(ValueError):
    pass


def _aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise MemoryValidationError("recorded_at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryValidationError("recorded_at must include a timezone")
    return parsed


def classify_memory(user_text: str) -> str:
    """A deliberately small fallback classifier; extraction remains responsible for candidacy."""
    text = user_text.replace(" ", "")
    if any(token in text for token in ("好き", "嫌い", "苦手", "好み")):
        return "preference"
    if any(token in text for token in ("明日", "来週", "来月", "予定", "つもり", "行く", "やる")):
        return "plan"
    if any(token in text for token in ("今日", "昨日", "一昨日", "去年", "数年前", "先週", "夏", "春", "秋", "冬", "話した", "作ってた", "やった")):
        return "episode"
    if any(token in text for token in ("今", "眠い", "疲れた", "元気", "体調")):
        return "state"
    return "fact"


def normalize_time(user_text: str, reference: datetime) -> dict:
    """Keep only the precision the user supplied; never invent a missing day/year."""
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise MemoryValidationError("reference timestamp must include a timezone")
    text = user_text.replace(" ", "")
    day = reference.date()
    if "一昨日" in text:
        return {"event_start": (day - timedelta(days=2)).isoformat(), "event_end": None, "time_precision": "day", "time_text": "一昨日"}
    if "昨日" in text:
        return {"event_start": (day - timedelta(days=1)).isoformat(), "event_end": None, "time_precision": "day", "time_text": "昨日"}
    if "明日" in text:
        return {"event_start": (day + timedelta(days=1)).isoformat(), "event_end": None, "time_precision": "day", "time_text": "明日"}
    if "今日" in text:
        return {"event_start": day.isoformat(), "event_end": None, "time_precision": "day", "time_text": "今日"}
    if "今" in text:
        return {"event_start": reference.replace(second=0, microsecond=0).isoformat(), "event_end": None, "time_precision": "minute", "time_text": "今"}
    if "去年の夏" in text:
        return {"event_start": f"{reference.year - 1}-summer", "event_end": None, "time_precision": "season", "time_text": "去年の夏"}
    if "数年前" in text:
        return {"event_start": None, "event_end": None, "time_precision": "unknown", "time_text": "数年前"}
    for season in ("春", "夏", "秋", "冬"):
        if season in text:
            return {"event_start": None, "event_end": None, "time_precision": "season", "time_text": season}
    return {"event_start": None, "event_end": None, "time_precision": "unknown", "time_text": None}


def normalize_v2(record: dict) -> dict:
    """Validate a new v2 record without making historical data look more certain."""
    if not isinstance(record, dict):
        raise MemoryValidationError("memory must be an object")
    content = record.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 200:
        raise MemoryValidationError("memory content is invalid")
    if record.get("memory_type") not in MEMORY_TYPES:
        raise MemoryValidationError("memory_type is invalid")
    confidence = record.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise MemoryValidationError("confidence must be between 0 and 1")
    source_turn_ids = record.get("source_turn_ids")
    if not isinstance(source_turn_ids, list) or not source_turn_ids or any(not isinstance(value, str) or not value for value in source_turn_ids):
        raise MemoryValidationError("source_turn_ids must contain real turn IDs")
    if len(set(source_turn_ids)) != len(source_turn_ids):
        raise MemoryValidationError("source_turn_ids must not duplicate IDs")
    _aware(record.get("recorded_at"))
    if record.get("time_precision") not in TIME_PRECISIONS:
        raise MemoryValidationError("time_precision is invalid")
    for key in ("event_start", "event_end", "time_text"):
        if record.get(key) is not None and not isinstance(record.get(key), str):
            raise MemoryValidationError(f"{key} must be a string or null")
    if record.get("status") != STATUS or record.get("schema_version") != 2:
        raise MemoryValidationError("v2 schema/status is invalid")
    return dict(record, content=content.strip(), confidence=float(confidence))


def normalize_for_read(record: dict) -> dict:
    """Return a safe view of a mixed store; legacy fields are never inferred."""
    if not isinstance(record, dict):
        raise MemoryValidationError("memory record is not an object")
    if record.get("schema_version") == 2:
        return normalize_v2(record)
    legacy = dict(record)
    legacy["schema_version"] = 1
    legacy["legacy"] = True
    legacy["provenance_status"] = "legacy_unverified"
    return legacy
