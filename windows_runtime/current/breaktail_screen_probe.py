"""Bounded, read-only UI Automation snapshot for the desktop pet.

Only control types and rough screen regions leave this process. Labels, field
values, document titles, and typed text are never returned or persisted.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import ctypes
import json
import os
from pathlib import Path
import sys


def _load_uia():
    local = Path(__file__).resolve().parent.parent / "pet_deps"
    if local.is_dir():
        sys.path.insert(0, str(local))
    override = os.environ.get("BREAKTAIL_PET_DEPS")
    if override:
        sys.path.insert(0, override)
    import uiautomation as ui
    return ui


def inspect_window(hwnd: int, *, max_nodes: int = 96, max_depth: int = 3) -> dict:
    ui = _load_uia()
    root = ui.ControlFromHandle(hwnd)
    if not root:
        return {"available": False}
    types, regions, depths = Counter(), Counter(), Counter()
    width = max(1, ctypes.windll.user32.GetSystemMetrics(0))
    nodes = deque([(root, 0)])
    visited = 0
    while nodes and visited < max_nodes:
        control, depth = nodes.popleft()
        visited += 1
        depths[str(depth)] += 1
        try:
            kind = str(control.ControlTypeName or "Unknown")
            rect = control.BoundingRectangle
            center = (rect.left + rect.right) / 2
            region = "left" if center < width / 3 else "right" if center > width * 2 / 3 else "center"
            types[kind] += 1
            regions[region] += 1
            if depth < max_depth:
                nodes.extend((child, depth + 1) for child in control.GetChildren()[:max_nodes - visited])
        except (OSError, RuntimeError, ValueError, AttributeError):
            continue
    try:
        focus = str(ui.GetFocusedControl().ControlTypeName or "Unknown")
    except (OSError, RuntimeError, ValueError, AttributeError):
        focus = "Unknown"
    return {"available": True, "types": dict(types.most_common(12)),
            "regions": dict(regions), "depths": dict(depths), "focused_type": focus,
            "nodes": visited, "limited": bool(nodes)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--handle", type=int, required=True)
    args = parser.parse_args()
    try:
        result = inspect_window(args.handle)
    except Exception:
        result = {"available": False}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

