"""Luculia-shaped reference boundary, intentionally inactive in Breaktail.

Luculia is not a dependency of this project.  As with FIO, capabilities become
available only after a real, explicitly supplied callable is verified.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from breaktail_bus import ActionRequest, ActionResult
from breaktail_capabilities import CapabilityRegistry


class LuculiaAdapter:
    source = "luculia"

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[ActionRequest], Any]] = {}

    def register_verified(self, capability: str, handler: Callable[[ActionRequest], Any], registry: CapabilityRegistry) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if capability in self._handlers:
            raise ValueError(f"Luculia capability already registered: {capability}")
        self._handlers[capability] = handler
        registry.register(capability, self)

    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def handle(self, request: ActionRequest) -> ActionResult:
        handler = self._handlers.get(request.capability)
        if handler is None:
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=False, error="Luculia capability is not verified or registered")
        try:
            value = handler(request)
            payload = value if isinstance(value, dict) else {"value": value}
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=True, payload=payload,
                                evidence=[{"kind": "provider_return", "provider": self.source}])
        except Exception as exc:
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=False, error=f"Luculia handler failed: {type(exc).__name__}: {exc}")
