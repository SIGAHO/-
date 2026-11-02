"""Canonical persistence paths for Breaktail production and isolated tests."""

import os
import sys
import tempfile
from pathlib import Path


STORE_DIRS = ("raw", "memory", "trace", "profile", "review", "training", "teacher", "cache", "state", "errors")


def _is_test_process() -> bool:
    return "unittest" in sys.modules or "pytest" in sys.modules or any(
        name.startswith("test_") for name in (Path(arg).name for arg in sys.argv)
    )


def resolve_data_root() -> Path:
    """Resolve once: explicit root, isolated test root, then stable install root."""
    configured = os.environ.get("BREAKTAIL_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if _is_test_process():
        root = Path(tempfile.gettempdir()) / f"breaktail-tests-{os.getpid()}"
        print(f"[breaktail] BREAKTAIL_DATA_ROOT未指定のテストを隔離: {root}", file=sys.stderr)
        return root
    return Path(__file__).resolve().parent.parent / "data"


DATA_ROOT = resolve_data_root()


def store_path(directory: str, filename: str, override_env: str | None = None) -> Path:
    """Per-store override wins; otherwise every store is rooted at DATA_ROOT."""
    if override_env and os.environ.get(override_env):
        return Path(os.environ[override_env]).expanduser().resolve()
    return DATA_ROOT / directory / filename


def ensure_data_root() -> None:
    for name in STORE_DIRS:
        (DATA_ROOT / name).mkdir(parents=True, exist_ok=True)


def path_report() -> dict[str, str]:
    return {"data_root": str(DATA_ROOT.resolve())}
