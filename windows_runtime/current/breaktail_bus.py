"""Process-local event contracts for optional Breaktail integrations.

The bus is deliberately transport-free.  It only coordinates in-process Python
objects; an HTTP, stdio, or MCP bridge can translate these dataclasses later.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Literal
from uuid import uuid4


EventKind = Literal["observation", "action_request", "action_result"]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, kw_only=True)
class BusEvent:
    source: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_timestamp)
    confidence: float | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source or not self.capability:
            raise ValueError("source and capability are required")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, kw_only=True)
class Observation(BusEvent):
    kind: Literal["observation"] = "observation"


@dataclass(frozen=True, kw_only=True)
class ActionRequest(BusEvent):
    kind: Literal["action_request"] = "action_request"


@dataclass(frozen=True, kw_only=True)
class ActionResult(BusEvent):
    success: bool
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    kind: Literal["action_result"] = "action_result"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.success and self.error:
            raise ValueError("a successful ActionResult cannot contain an error")
        if not self.success and not self.error:
            raise ValueError("a failed ActionResult requires an error")


Subscriber = Callable[[BusEvent], None]
ActionHandler = Callable[[ActionRequest], ActionResult]


class EventBus:
    """Small synchronous bus with explicit action handlers and audit history."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._handlers: dict[str, ActionHandler] = {}
        self._history: list[BusEvent] = []
        self._lock = RLock()

    def subscribe(self, event_kind: EventKind | str, subscriber: Subscriber) -> Callable[[], None]:
        if not callable(subscriber):
            raise TypeError("subscriber must be callable")
        with self._lock:
            self._subscribers.setdefault(event_kind, []).append(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                listeners = self._subscribers.get(event_kind, [])
                if subscriber in listeners:
                    listeners.remove(subscriber)
        return unsubscribe

    def publish(self, event: BusEvent) -> BusEvent:
        with self._lock:
            self._history.append(event)
            listeners = tuple(self._subscribers.get(event.kind, ())) + tuple(self._subscribers.get("*", ()))
        for listener in listeners:
            listener(event)
        return event

    def register_action_handler(self, capability: str, handler: ActionHandler) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            if capability in self._handlers:
                raise ValueError(f"action handler already registered: {capability}")
            self._handlers[capability] = handler

    def request(self, request: ActionRequest) -> ActionResult:
        self.publish(request)
        with self._lock:
            handler = self._handlers.get(request.capability)
        if handler is None:
            result = ActionResult(source="breaktail_bus", capability=request.capability,
                                  trace_id=request.trace_id, success=False,
                                  error=f"no action handler registered for: {request.capability}")
        else:
            try:
                result = handler(request)
                if not isinstance(result, ActionResult):
                    raise TypeError("action handler must return ActionResult")
                if result.trace_id != request.trace_id:
                    raise ValueError("action result trace_id must match its request")
            except Exception as exc:
                result = ActionResult(source="breaktail_bus", capability=request.capability,
                                      trace_id=request.trace_id, success=False,
                                      error=f"handler error: {type(exc).__name__}: {exc}")
        return self.publish(result)  # type: ignore[return-value]

    def history(self) -> tuple[BusEvent, ...]:
        with self._lock:
            return tuple(self._history)
