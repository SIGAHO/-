"""Small code-owned runtime fact store for Breaktail.

Facts are process-local observations.  They are never learned from model text and
are not persisted into Memory/Raw/Trace stores.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import socket
import sys
import shutil
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


FACT_STATUSES = {"ok", "stale", "failed", "not_connected", "unknown"}


def _now() -> datetime:
    return datetime.now().astimezone()


def _as_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RuntimeFact:
    key: str
    value: object
    observed_at: str
    source: str
    status: str = "ok"
    ttl_seconds: float = 0

    def __post_init__(self):
        if not self.key or not self.source:
            raise ValueError("RuntimeFact requires key and source")
        if self.status not in FACT_STATUSES:
            raise ValueError(f"invalid RuntimeFact status: {self.status}")
        if self.ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        _as_datetime(self.observed_at)

    def at(self, now: datetime | None = None) -> "RuntimeFact":
        """Return a view with an expired successful observation marked stale."""
        if self.status != "ok" or self.ttl_seconds == 0:
            return self
        age = ((now or _now()) - _as_datetime(self.observed_at).astimezone((now or _now()).tzinfo)).total_seconds()
        return replace(self, status="stale") if age > self.ttl_seconds else self

    def as_dict(self, now: datetime | None = None) -> dict:
        fact = self.at(now)
        return {"key": fact.key, "value": fact.value, "observed_at": fact.observed_at,
                "source": fact.source, "status": fact.status, "ttl_seconds": fact.ttl_seconds}


@dataclass(frozen=True)
class OperationResult:
    operation: str
    requested_at: str
    executed: bool
    verified: bool
    status: str
    verification_source: str | None
    result_summary: str

    @property
    def successful(self) -> bool:
        return self.executed is True and self.verified is True and self.status == "ok"

    def as_dict(self) -> dict:
        return {"operation": self.operation, "requested_at": self.requested_at,
                "executed": self.executed, "verified": self.verified,
                "status": self.status, "verification_source": self.verification_source,
                "result_summary": self.result_summary, "successful": self.successful}


class FactStore:
    """Thread-safe, in-memory snapshot store.  It never writes Production data."""

    def __init__(self):
        self._facts: dict[str, RuntimeFact] = {}
        self._current_operation: OperationResult | None = None
        self._last_operation: OperationResult | None = None
        self._lock = threading.RLock()

    def put(self, fact: RuntimeFact) -> RuntimeFact:
        with self._lock:
            self._facts[fact.key] = fact
        return fact

    def get(self, key: str, now: datetime | None = None) -> RuntimeFact | None:
        with self._lock:
            fact = self._facts.get(key)
        return fact.at(now) if fact else None

    def snapshot(self, keys: set[str] | list[str], now: datetime | None = None) -> list[dict]:
        return [fact.as_dict(now) for key in sorted(keys) if (fact := self.get(key, now)) is not None]

    def start_operation(self, operation: str, requested_at: str | None = None) -> OperationResult:
        result = OperationResult(operation, requested_at or _now().isoformat(), False, False,
                                 "unknown", None, "requested; not executed or verified")
        with self._lock:
            self._current_operation = result
        return result

    def finish_operation(self, operation: str, *, executed: bool, verified: bool,
                         status: str, verification_source: str | None,
                         result_summary: str, requested_at: str | None = None) -> OperationResult:
        with self._lock:
            started = self._current_operation
            requested = (started.requested_at if started and started.operation == operation
                         else requested_at or _now().isoformat())
            result = OperationResult(operation, requested, executed, verified, status,
                                     verification_source, result_summary)
            self._last_operation = result
            self._current_operation = None
        return result

    def operation_facts(self, now: datetime | None = None) -> list[RuntimeFact]:
        observed = (now or _now()).isoformat()
        with self._lock:
            current, last = self._current_operation, self._last_operation
        return [
            RuntimeFact("operation.current", current.as_dict() if current else None, observed,
                        "runtime_operation_tracker", "ok" if current else "unknown", 0),
            RuntimeFact("operation.last_result", last.as_dict() if last else None, observed,
                        "runtime_operation_tracker", "ok" if last else "unknown", 0),
        ]


RUNTIME_FACTS = FactStore()


def fact(key: str, value: object, source: str, *, status: str = "ok",
         ttl_seconds: float = 0, observed_at: str | None = None) -> RuntimeFact:
    return RuntimeFact(key, value, observed_at or _now().isoformat(), source, status, ttl_seconds)


def collect_clock(now: datetime | None = None) -> list[RuntimeFact]:
    now = now or _now()
    offset = now.strftime("%z")
    values = {
        "current_datetime_iso": now.isoformat(), "current_date": now.date().isoformat(),
        "current_year": now.year, "current_time": now.strftime("%H:%M"),
        "timezone": {"offset": offset[:3] + ":" + offset[3:], "label": now.tzname()},
    }
    return [fact(f"clock.{key}", value, "os_runtime_clock", ttl_seconds=1,
                 observed_at=now.isoformat()) for key, value in values.items()]


def collect_capabilities(capabilities: dict, now: datetime | None = None) -> RuntimeFact:
    return fact("capabilities", capabilities, "trusted_runtime_adapters", ttl_seconds=1,
                observed_at=(now or _now()).isoformat())


def collect_system_memory(now: datetime | None = None) -> RuntimeFact:
    observed = (now or _now()).isoformat()
    try:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            state = MemoryStatus()
            state.dwLength = ctypes.sizeof(MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                raise OSError("GlobalMemoryStatusEx failed")
            total, available = int(state.ullTotalPhys), int(state.ullAvailPhys)
        else:
            page = os.sysconf("SC_PAGE_SIZE")
            total = int(page * os.sysconf("SC_PHYS_PAGES"))
            available = int(page * os.sysconf("SC_AVPHYS_PAGES"))
        used = total - available
        gib = 1024 ** 3
        value = {"total_bytes": total, "used_bytes": used, "available_bytes": available,
                 "total_gib": round(total / gib, 2), "used_gib": round(used / gib, 2),
                 "available_gib": round(available / gib, 2),
                 "used_percent": round(used * 100 / total, 1) if total else None}
        return RuntimeFact("system.memory", value, observed, "os_memory_api", "ok", 5)
    except Exception as error:
        return RuntimeFact("system.memory", None, observed, "os_memory_api", "failed", 5)


def collect_system_identity(now: datetime | None = None) -> RuntimeFact:
    """Read stable local runtime identity without probing network or user data."""
    observed = (now or _now()).isoformat()
    try:
        value = {
            "os": platform.system() or os.name,
            "os_release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
        return RuntimeFact("system.identity", value, observed, "os_platform_api", "ok", 60)
    except Exception:
        return RuntimeFact("system.identity", None, observed, "os_platform_api", "failed", 60)


def collect_system_disk(now: datetime | None = None) -> RuntimeFact:
    """Read only aggregate capacity for the runtime drive, never file names."""
    observed = (now or _now()).isoformat()
    try:
        root = Path.cwd().anchor or Path.cwd().drive or str(Path.cwd())
        usage = shutil.disk_usage(root)
        gib = 1024 ** 3
        value = {
            "root": root, "total_gib": round(usage.total / gib, 2),
            "used_gib": round(usage.used / gib, 2), "free_gib": round(usage.free / gib, 2),
        }
        return RuntimeFact("system.disk", value, observed, "os_disk_usage_api", "ok", 5)
    except OSError:
        return RuntimeFact("system.disk", None, observed, "os_disk_usage_api", "failed", 5)


def collect_system_cpu(now: datetime | None = None) -> RuntimeFact:
    """Read only the logical CPU count exposed to this runtime."""
    observed = (now or _now()).isoformat()
    try:
        logical_count = os.cpu_count()
        if not isinstance(logical_count, int) or logical_count < 1:
            raise OSError("logical CPU count unavailable")
        return RuntimeFact("system.cpu", {"logical_count": logical_count}, observed,
                           "os_cpu_api", "ok", 5)
    except OSError:
        return RuntimeFact("system.cpu", None, observed, "os_cpu_api", "failed", 5)


def collect_memory_state(path: Path, now: datetime | None = None) -> RuntimeFact:
    observed = (now or _now()).isoformat()
    try:
        if not path.exists():
            value = {"count": 0, "last_saved_at": None}
        else:
            count = 0
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        json.loads(line)
                        count += 1
            value = {"count": count, "last_saved_at": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).astimezone().isoformat()}
        return RuntimeFact("memory.state", value, observed, "memory_store_metadata", "ok", 5)
    except (OSError, ValueError, json.JSONDecodeError):
        return RuntimeFact("memory.state", None, observed, "memory_store_metadata", "failed", 5)


def collect_context_state(history_count: int, max_history_messages: int, num_ctx: int,
                          trim_occurred: bool = False, now: datetime | None = None) -> RuntimeFact:
    value = {"history_message_count": history_count, "max_history_messages": max_history_messages,
             "trim_occurred": bool(trim_occurred), "num_ctx": num_ctx,
             "usage": "exact prompt token usage is available only after model execution"}
    return fact("context.state", value, "reply_context_builder", ttl_seconds=1,
                observed_at=(now or _now()).isoformat())


def collect_last_error(error_sources: dict[str, object] | None, now: datetime | None = None) -> RuntimeFact:
    errors = {key: value for key, value in (error_sources or {}).items() if value}
    return fact("last_error", {"errors": errors} if errors else {"errors": {}},
                "code_owned_error_state", status="ok" if errors else "unknown", ttl_seconds=1,
                observed_at=(now or _now()).isoformat())


def collect_local_service(key: str, host: str, port: int, now: datetime | None = None,
                          timeout: float = 0.15) -> RuntimeFact:
    observed = (now or _now()).isoformat()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return RuntimeFact(key, None, observed, "local_tcp_probe", "unknown", 2)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return RuntimeFact(key, {"reachable": True, "host": host, "port": port},
                               observed, "local_tcp_probe", "ok", 2)
    except ConnectionRefusedError:
        return RuntimeFact(key, {"reachable": False, "host": host, "port": port},
                           observed, "local_tcp_probe", "not_connected", 2)
    except (TimeoutError, OSError) as error:
        return RuntimeFact(key, {"reachable": None, "host": host, "port": port,
                                 "error_type": type(error).__name__},
                           observed, "local_tcp_probe", "failed", 2)


def ollama_endpoint(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    return parsed.hostname, parsed.port or 80

