from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import time
import uuid


class SourceType(str, Enum):
    RUNTIME = "runtime"
    USER_CORRECTION = "user_correction"
    USER_STATEMENT = "user_statement"
    VERIFIED_MEMORY = "verified_memory"
    SYSTEM = "system"
    ASSISTANT_GENERATED = "assistant_generated"


class Scope(str, Enum):
    TURN = "turn"
    SESSION = "session"
    PROJECT = "project"
    LONG_TERM = "long_term"


class Status(str, Enum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


@dataclass
class Event:
    kind: str
    payload: dict[str, Any]
    source: SourceType
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        return d


@dataclass
class Fact:
    key: str
    value: Any
    source: SourceType
    scope: Scope
    status: Status = Status.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    superseded_by: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["scope"] = self.scope.value
        d["status"] = self.status.value
        return d


@dataclass
class MemoryItem:
    text: str
    source: SourceType
    importance: float = 0.5
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    mentions: int = 1
    status: Status = Status.ACTIVE
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Topic:
    label: str
    signature: set[str]
    score: float
    last_seen: float = field(default_factory=time.time)


@dataclass
class OpenLoop:
    text: str
    created_at: float = field(default_factory=time.time)
    done: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
