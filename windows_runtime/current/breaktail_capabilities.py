"""Registry that keeps Breaktail independent of concrete integration providers."""
from __future__ import annotations

from threading import RLock
from typing import Any


class CapabilityError(LookupError):
    pass


class CapabilityAlreadyRegisteredError(CapabilityError):
    pass


class CapabilityNotFoundError(CapabilityError):
    pass


class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._lock = RLock()

    def register(self, capability: str, provider: Any) -> Any:
        if not isinstance(capability, str) or not capability.strip():
            raise ValueError("capability must be a non-empty string")
        if provider is None:
            raise ValueError("provider must not be None")
        with self._lock:
            if capability in self._providers:
                raise CapabilityAlreadyRegisteredError(f"capability already registered: {capability}")
            self._providers[capability] = provider
        return provider

    def resolve(self, capability: str) -> Any:
        with self._lock:
            try:
                return self._providers[capability]
            except KeyError as exc:
                raise CapabilityNotFoundError(f"capability is not registered: {capability}") from exc

    def list_capabilities(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._providers))


default_registry = CapabilityRegistry()

def register(capability: str, provider: Any) -> Any:
    return default_registry.register(capability, provider)

def resolve(capability: str) -> Any:
    return default_registry.resolve(capability)

def list_capabilities() -> tuple[str, ...]:
    return default_registry.list_capabilities()
