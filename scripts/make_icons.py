#!/usr/bin/env python3
"""Generate the PWA icons (no third-party deps).

Draws a simple "marked essay page" glyph: a white page with blue text lines and
a teal check, on the app's blue. Run from anywhere:

    python3 scripts/make_icons.py

Writes server/aitutor_server/static/icons/{icon-192,icon-512,icon-512-maskable}.png
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

BLUE = (31, 84, 196)
PAGE = (255, 255, 255)
LINE = (59, 130, 246)
CHECK = (15, 138, 107)

OUT = Path(__file__).resolve().parents[1] / "server/aitutor_server/static/icons"


def _png(path: Path, size: int, px: bytearray) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        raw += px[y * size * 4:(y + 1) * size * 4]
    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
    path.write_bytes(blob)


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def render(size: int, pad_frac: float) -> bytearray:
    """Background -> white page -> text lines -> check, in paint order."""
    px = bytearray(size * size * 4)

    def put(x, y, rgb):
        i = (y * size + x) * 4
        px[i:i + 4] = bytes((*rgb, 255))

    for y in range(size):
        for x in range(size):
            put(x, y, BLUE)

    pad = int(size * pad_frac)
    px0, py0, px1, py1 = pad, pad, size - pad, size - pad
    pw = px1 - px0
    radius = pw * 0.10

    def in_page(x, y):
        if not (px0 <= x < px1 and py0 <= y < py1):
            return False
        if (x < px0 + radius or x > px1 - radius) and (y < py0 + radius or y > py1 - radius):
            cx = px0 + radius if x < px0 + radius else px1 - radius
            cy = py0 + radius if y < py0 + radius else py1 - radius
            return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2
        return True

    for y in range(py0, py1):
        for x in range(px0, px1):
            if in_page(x, y):
                put(x, y, PAGE)

    line_w = max(2, int(pw * 0.085))
    line_x0 = px0 + int(pw * 0.16)
    line_x1 = px1 - int(pw * 0.16)
    for r in (0.30, 0.45, 0.60, 0.75):
        ly = int(py0 + pw * r)
        lx1 = line_x1 - (int(pw * 0.30) if r >= 0.60 else 0)
        for y in range(ly - line_w // 2, ly + line_w // 2):
            for x in range(line_x0, lx1):
                if in_page(x, y):
                    put(x, y, LINE)

    t = pw * 0.055
    ax, ay = px0 + pw * 0.58, py0 + pw * 0.72
    bx, by = px0 + pw * 0.69, py0 + pw * 0.84
    cx, cy = px0 + pw * 0.92, py0 + pw * 0.52
    for y in range(py0, py1):
        for x in range(px0, px1):
            if in_page(x, y) and min(
                _seg_dist(x, y, ax, ay, bx, by), _seg_dist(x, y, bx, by, cx, cy)
            ) <= t:
                put(x, y, CHECK)

    return px


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _png(OUT / "icon-192.png", 192, render(192, 0.16))
    _png(OUT / "icon-512.png", 512, render(512, 0.16))
    _png(OUT / "icon-512-maskable.png", 512, render(512, 0.26))
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
