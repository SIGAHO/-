"""FIO boundary placeholder.

No FIO implementation is present in the Breaktail project, so this module does
not invent or auto-register FIO capabilities.  A future adapter must map a
verified FIO callable explicitly using ``register_verified``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from breaktail_bus import ActionRequest, ActionResult
from breaktail_capabilities import CapabilityRegistry


class FioAdapter:
    source = "fio"

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[ActionRequest], Any]] = {}

    def register_verified(self, capability: str, handler: Callable[[ActionRequest], Any], registry: CapabilityRegistry) -> None:
        """Register only a callable verified against a real FIO implementation."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        if capability in self._handlers:
            raise ValueError(f"FIO capability already registered: {capability}")
        self._handlers[capability] = handler
        registry.register(capability, self)

    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def handle(self, request: ActionRequest) -> ActionResult:
        handler = self._handlers.get(request.capability)
        if handler is None:
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=False, error="FIO capability is not verified or registered")
        try:
            value = handler(request)
            payload = value if isinstance(value, dict) else {"value": value}
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=True, payload=payload,
                                evidence=[{"kind": "provider_return", "provider": self.source}])
        except Exception as exc:
            return ActionResult(source=self.source, capability=request.capability, trace_id=request.trace_id,
                                success=False, error=f"FIO handler failed: {type(exc).__name__}: {exc}")
