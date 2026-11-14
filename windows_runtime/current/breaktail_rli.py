"""Decode the PNG layers and timing of a small RealWorld layered animation."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import struct

from PIL import Image


def _chunks(data: bytes, start: int, end: int):
    while start + 8 <= end:
        tag = data[start:start + 4]
        size = int.from_bytes(data[start + 4:start + 8], "little")
        stop = start + 8 + size
        if stop > end:
            raise ValueError("invalid RLI chunk length")
        yield tag, data[start + 8:stop]
        start += 8 + ((size + 3) & ~3)


def load_rli(path: Path) -> list[tuple[Image.Image, int]]:
    data = path.read_bytes()
    if len(data) > 4_000_000 or not data.startswith(b"RWLayeredImage_1"):
        raise ValueError("unsupported RLI")
    frames = []
    layers = []
    duration = 100
    canvas_size = (128, 128)

    def finish_frame():
        if not layers:
            return
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        for layer in layers:
            if layer.size != canvas_size:
                raise ValueError("unsupported layer size")
            canvas.alpha_composite(layer)
        frames.append((canvas, duration))
        layers.clear()

    for tag, payload in _chunks(data, 16, len(data)):
        if tag == b"FRMI":
            finish_frame()
            if len(frames) >= 60 or len(payload) != 4:
                raise ValueError("unsupported animation")
            duration = max(40, min(2000, round(struct.unpack("<f", payload)[0] * 1000)))
        elif tag == b"CNVS":
            if len(payload) < 8:
                raise ValueError("invalid canvas")
            canvas_size = struct.unpack_from("<II", payload)
            if not all(1 <= side <= 512 for side in canvas_size):
                raise ValueError("unsupported canvas size")
        elif tag == b"LAER":
            if len(layers) >= 16:
                raise ValueError("too many layers")
            for subtag, content in _chunks(payload, 0, len(payload)):
                if subtag == b"DOCU" and content.startswith(b"\x89PNG\r\n\x1a\n"):
                    with Image.open(BytesIO(content)) as source:
                        layers.append(source.convert("RGBA"))
                    break
    finish_frame()
    if not frames:
        raise ValueError("RLI contains no PNG frames")
    return frames

