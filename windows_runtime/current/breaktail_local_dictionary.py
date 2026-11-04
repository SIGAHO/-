"""Read a small, versioned local technical dictionary without a model or network.

This is deliberately a bounded fact source, not an attempt to make the model
pretend it has a complete Japanese dictionary.  Unknown words return ``None``
and continue to normal generation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


_DICTIONARY_FILE = Path(__file__).resolve().parent / "resources" / "local_technical_dictionary.json"


def _entries() -> dict[str, str]:
    try:
        data = json.loads(_DICTIONARY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("entries", {}) if isinstance(data, dict) else {}
    return {str(key).lower(): value for key, value in entries.items() if isinstance(value, str)}


def local_definition_reply(user_text: str) -> str | None:
    """Return a definition only for an exact bundled term and explicit query."""
    text = (user_text or "").strip()
    match = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9._+-]{1,31})\s*(?:って何|とは何|とは|の意味|ってどういう意味)[？?]?\s*", text, re.I)
    if not match:
        return None
    term = match.group(1)
    definition = _entries().get(term.lower())
    return f"{term}: {definition}" if definition else None
