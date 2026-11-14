"""Small, model-independent controller for Breaktail's confirmed self-profile.

Only a profile explicitly accepted by the user is persisted here. The user's
raw conversation is never written to this file.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from breaktail_paths import store_path


PROFILE_FILE = store_path("profile", "breaktail_self_profile.json", "BREAKTAIL_PROFILE_FILE")
_PROFILE_LINE = re.compile(r"^\s*(\d{1,2})[.．)、]\s*([^:：]+)[:：]\s*(.+?)\s*$")
_PROFILE_TARGET = re.compile(r"(?:Breaktail|ブレイクテール|お前|君)のプロフィール", re.I)
_REMEMBER_REQUEST = re.compile(r"覚えておいて|覚えといて|覚えてて|記憶して|忘れないで")


class ProfileStoreError(RuntimeError):
    """The external profile could not be validated, saved, or read back."""


def is_remember_request(text: str) -> bool:
    match=_REMEMBER_REQUEST.search(text)
    if not match:
        return False
    # A persistence shortcut must not swallow another question in the same
    # message. Mixed requests stay in the ordinary conversation path.
    rest=text[match.end():]
    return not bool(re.search(r'[？?]|教えて|答えて|説明して|確認して|どうな|どこ|いつ|何を',rest))


def is_profile_commit_request(text: str) -> bool:
    return is_remember_request(text) and bool(_PROFILE_TARGET.search(text))


def extract_recent_profile(history: list[dict]) -> list[dict] | None:
    """Find the latest complete numbered profile written by Breaktail in RAM."""
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        items = {}
        for line in message.get("content", "").splitlines():
            match = _PROFILE_LINE.match(line)
            if not match:
                continue
            index = int(match.group(1))
            label, value = match.group(2).strip(), match.group(3).strip()
            if index in items or not label or not value:
                items = {}
                break
            items[index] = {"number": index, "label": label, "value": value}
        if sorted(items) == list(range(1, 21)):
            return [items[index] for index in range(1, 21)]
    return None


def _validate_profile(data: object) -> dict:
    if not isinstance(data, dict) or data.get("kind") != "self_profile":
        raise ProfileStoreError("保存済みプロフィールの形式が正しくありません。")
    if data.get("subject") != "breaktail" or data.get("confirmed_by_user") is not True:
        raise ProfileStoreError("ユーザーが確定していないプロフィールは使えません。")
    items = data.get("items")
    if not isinstance(items, list) or len(items) != 20:
        raise ProfileStoreError("プロフィールが20項目そろっていません。")
    for number, item in enumerate(items, 1):
        if (not isinstance(item, dict) or item.get("number") != number
                or not isinstance(item.get("label"), str) or not item["label"].strip()
                or not isinstance(item.get("value"), str) or not item["value"].strip()):
            raise ProfileStoreError("プロフィールの項目を読み取れません。")
    return data


def load_profile(path: Path | None = None) -> dict | None:
    path = path or PROFILE_FILE
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            return _validate_profile(json.load(stream))
    except (OSError, ValueError, TypeError) as error:
        raise ProfileStoreError("保存済みプロフィールを読み込めません。") from error


def save_verified_profile(items: list[dict], path: Path | None = None) -> dict:
    """Atomically write, then read back before claiming the profile was saved."""
    path = path or PROFILE_FILE
    previous = load_profile(path)
    record = _validate_profile({
        "version": (previous.get("version", 0) + 1) if previous else 1,
        "kind": "self_profile",
        "subject": "breaktail",
        "confirmed_by_user": True,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    })
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".breaktail-profile-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        if load_profile(path) != record:
            raise ProfileStoreError("プロフィールを書き込みましたが、読み戻し確認に失敗しました。")
        return record
    except OSError as error:
        raise ProfileStoreError("プロフィールを保存できませんでした。覚えたとは言えません。") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def profile_context(profile: dict | None) -> str:
    if profile is None:
        return ""
    return "\n".join(f"{item['label']}: {item['value']}" for item in profile["items"])
