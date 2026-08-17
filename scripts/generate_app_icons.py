"""Generate the Klaus app icons — no image libraries required.

The mark follows the style Amit picked (Conductor's icon): a dark ground, a
white rounded plate inset in it, and the glyph punched out of the plate as
chunky pixel blocks. Klaus's glyph is a 5×5 block "K".

Anti-aliasing is analytic — every shape is a signed distance field sampled
with a one-pixel ramp — so edges are clean without supersampling, and the
whole thing is pure stdlib (zlib + struct).

Run:  .venv/bin/python -m scripts.generate_app_icons
Outputs (frontend/public/): icon-192.png, icon-512.png,
icon-512-maskable.png, apple-touch-icon.png

Re-run after any brand change; the source of truth is this file, not the PNGs.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

# Paper Hub palette (frontend/src/tokens.ts)
MIDNIGHT = (0x1C, 0x25, 0x40)
PAPER = (0xF7, 0xF7, 0xF9)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public"

# The plate: a rounded square centred in the canvas, as a fraction of it.
_PLATE_SIZE = 0.66
_PLATE_RADIUS = 0.145      # corner radius, fraction of canvas

# The glyph: a 5×5 block "K" punched out of the plate.
_GLYPH = [
    "#···#",
    "#··#·",
    "###··",
    "#··#·",
    "#···#",
]
_GLYPH_INSET = 0.12        # padding inside the plate, fraction of plate size
_BLOCK_GAP = 0.13          # gap between blocks, fraction of a cell
_BLOCK_RADIUS = 0.22       # block corner radius, fraction of a block


def _rounded_rect_distance(
    px: float, py: float, cx: float, cy: float, half_w: float, half_h: float, radius: float
) -> float:
    """Signed distance from a point to a rounded rectangle (negative inside)."""
    dx = abs(px - cx) - half_w + radius
    dy = abs(py - cy) - half_h + radius
    outside = ((max(dx, 0.0) ** 2) + (max(dy, 0.0) ** 2)) ** 0.5
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius


def _coverage(distance: float, feather: float) -> float:
    """1 inside the shape, 0 outside, ramped across one pixel."""
    value = (feather / 2 - distance) / feather
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def _blend(base: tuple, over: tuple, alpha: float) -> tuple:
    return tuple(base[i] + (over[i] - base[i]) * alpha for i in range(3))


def _render(size: int, plate_scale: float) -> bytes:
    """Return raw RGB bytes for one icon.

    Args:
        size: Square edge length in pixels.
        plate_scale: Plate size relative to the default. Below 1.0 shrinks the
            mark toward the centre so a maskable crop cannot clip it.
    """
    feather = 1.0 / size
    half_plate = _PLATE_SIZE * plate_scale / 2
    plate_radius = _PLATE_RADIUS * plate_scale

    # Geometry of the glyph grid, in unit coordinates.
    rows, cols = len(_GLYPH), len(_GLYPH[0])
    grid_half = half_plate * (1 - _GLYPH_INSET)
    cell = (grid_half * 2) / max(rows, cols)
    block_half = cell * (1 - _BLOCK_GAP) / 2
    block_radius = block_half * 2 * _BLOCK_RADIUS
    grid_left = 0.5 - (cols * cell) / 2
    grid_top = 0.5 - (rows * cell) / 2

    # Pre-compute each block's centre so the inner loop stays cheap.
    blocks = [
        (grid_left + (col + 0.5) * cell, grid_top + (row + 0.5) * cell)
        for row, line in enumerate(_GLYPH)
        for col, mark in enumerate(line)
        if mark == "#"
    ]

    rows_out = bytearray()
    for y in range(size):
        rows_out.append(0)  # PNG filter byte: None
        py = (y + 0.5) / size
        for x in range(size):
            px = (x + 0.5) / size

            colour = MIDNIGHT

            # 1. The white plate.
            plate = _coverage(
                _rounded_rect_distance(px, py, 0.5, 0.5, half_plate, half_plate, plate_radius),
                feather,
            )
            if plate > 0:
                colour = _blend(colour, PAPER, plate)

                # 2. The glyph, punched back out of the plate.
                nearest = min(
                    (
                        _rounded_rect_distance(
                            px, py, bx, by, block_half, block_half, block_radius
                        )
                        for bx, by in blocks
                    ),
                    default=1.0,
                )
                block = _coverage(nearest, feather)
                if block > 0:
                    colour = _blend(colour, MIDNIGHT, block)

            for channel in range(3):
                rows_out.append(int(colour[channel] + 0.5))
    return bytes(rows_out)


def _write_png(path: Path, size: int, raw: bytes) -> None:
    """Write a minimal 8-bit RGB PNG."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit, truecolour
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # (filename, pixel size, plate scale)
    #   maskable shrinks the mark into the 80% safe zone Android/iOS may crop.
    targets = [
        ("icon-192.png", 192, 1.0),
        ("icon-512.png", 512, 1.0),
        ("icon-512-maskable.png", 512, 0.74),
        ("apple-touch-icon.png", 180, 1.0),
    ]
    for filename, size, plate_scale in targets:
        raw = _render(size, plate_scale)
        path = OUTPUT_DIR / filename
        _write_png(path, size, raw)
        print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)} ({size}×{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
