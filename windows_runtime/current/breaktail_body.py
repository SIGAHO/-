"""Small public body API; Bus/Registry providers stay an implementation detail."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from breaktail_bus import ActionRequest, ActionResult, EventBus, Observation
from breaktail_capabilities import CapabilityRegistry
from breaktail_neural_state import StateStore


@dataclass(frozen=True)
class BodyResult:
    ok: bool
    payload: dict[str, Any]
    error: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_action(cls, result: ActionResult) -> "BodyResult":
        return cls(result.success, dict(result.payload), result.error, tuple(result.evidence))


class _PullNamespace:
    def __init__(self, body: "BreaktailBody", capability: str) -> None:
        self._body, self._capability = body, capability

    def __call__(self, **payload: Any) -> BodyResult:
        return self._body._request(self._capability, payload)


class _ScreenAPI:
    def __init__(self, body: "BreaktailBody") -> None: self._body = body
    def look(self, **payload: Any) -> BodyResult: return self._body._request("screen.look", payload)


class _MemoryAPI:
    def __init__(self, body: "BreaktailBody") -> None: self._body = body
    def search(self, query: str, **payload: Any) -> BodyResult:
        return self._body._request("memory.search", {"query": query, **payload})


class _WebAPI:
    def __init__(self, body: "BreaktailBody") -> None: self._body = body
    def search(self, query: str, **payload: Any) -> BodyResult:
        return self._body._request("web.search", {"query": query, **payload})


class _FilesAPI:
    def __init__(self, body: "BreaktailBody") -> None: self._body = body
    def read(self, path: str, **payload: Any) -> BodyResult:
        return self._body._request("file.read", {"path": path, **payload})


class _ComputerAPI:
    def __init__(self, body: "BreaktailBody") -> None: self._body = body
    def action(self, **payload: Any) -> BodyResult: return self._body._request("computer.action", payload)


class BreaktailBody:
    def __init__(self, *, bus: EventBus | None = None, registry: CapabilityRegistry | None = None, state_store: StateStore | None = None) -> None:
        self.bus = bus or EventBus()
        self.registry = registry or CapabilityRegistry()
        self.state_store = state_store or StateStore()
        self.bus.subscribe("observation", self._on_observation)
        self.screen = _ScreenAPI(self)
        self.memory = _MemoryAPI(self)
        self.web = _WebAPI(self)
        self.files = _FilesAPI(self)
        self.computer = _ComputerAPI(self)

    def _on_observation(self, event: object) -> None:
        if isinstance(event, Observation):
            self.state_store.ingest(event)

    def publish(self, observation: Observation) -> Observation:
        self.bus.publish(observation)
        return observation

    def state(self) -> dict[str, Any]:
        return self.state_store.snapshot()

    snapshot = state

    def set_attention(self, attention: str | None, *, current_task: str | None = None, do_not_disturb: bool = False) -> None:
        self.state_store.set_attention(attention, current_task=current_task, do_not_disturb=do_not_disturb)

    def _request(self, capability: str, payload: dict[str, Any]) -> BodyResult:
        try:
            provider = self.registry.resolve(capability)
        except Exception as exc:
            return BodyResult(False, {}, str(exc))
        handler = getattr(provider, "handle", provider)
        try:
            self.bus.register_action_handler(capability, handler)
        except ValueError:
            pass  # Provider was already wired by the host.
        result = self.bus.request(ActionRequest(source="breaktail_body", capability=capability, payload=payload,
                                               provenance={"layer": "body_api"}))
        return BodyResult.from_action(result)
