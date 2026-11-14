"""Isolated OCR of one in-memory screenshot for the desktop pet.

No screenshot or recognized text is written to disk. Output is bounded and
redacts obvious contact details and secrets before returning to the pet.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
import sys
import time


def _deps():
    local = Path(__file__).resolve().parent.parent / "pet_ocr_deps"
    if local.is_dir():
        sys.path.insert(0, str(local))
    override = os.environ.get("BREAKTAIL_PET_OCR_DEPS")
    if override:
        sys.path.insert(0, override)


def safe_text(value: str) -> str:
    text = " ".join(str(value).split())[:80]
    if re.search(r"password|パスワード|認証コード|ワンタイム|api.?key|secret|token", text, re.I):
        return ""
    text = re.sub(r"https?://\S+|www\.\S+|[A-Za-z]:\\\S+|[\w.+-]+@[\w.-]+|\d{6,}",
                  "（省略）", text, flags=re.I)
    return text[:60]


def parse_result(result, width: int, height: int, elapsed: float) -> dict:
    lines = []
    boxes = result.boxes if result.boxes is not None else []
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    for box, text, score in zip(boxes, texts, scores):
        if float(score) < 0.65:
            continue
        cleaned = safe_text(text)
        if not cleaned:
            continue
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        if right <= left or bottom <= top:
            continue
        region = "left" if (left + right) / 2 < width / 3 else \
                 "right" if (left + right) / 2 > width * 2 / 3 else "center"
        lines.append({"text": cleaned, "score": round(float(score), 2),
                      "region": region,
                      "box": [round(left / width * 1000), round(top / height * 1000),
                              round(right / width * 1000), round(bottom / height * 1000)]})
        if len(lines) >= 25:
            break
    return {"available": True, "lines": lines, "count": len(lines),
            "elapsed_s": round(elapsed, 2)}


def recognize(image_bytes: bytes) -> dict:
    _deps()
    from PIL import Image
    width, height = Image.open(BytesIO(image_bytes)).size
    from rapidocr import RapidOCR
    start = time.perf_counter()
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        result = RapidOCR()(image_bytes)
    return parse_result(result, width, height, time.perf_counter() - start)


def main():
    image = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    if not image or len(image) > 4 * 1024 * 1024:
        print(json.dumps({"available": False, "reason": "image_size"}))
        return
    try:
        result = recognize(image)
    except Exception:
        result = {"available": False, "reason": "ocr_error"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

