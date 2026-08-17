"""Generate the Klaus app icons — no image libraries required.

Draws a geometric "K" monogram in paper white on the Paper Hub's midnight
accent and writes the four PNGs the PWA needs. Anti-aliasing is analytic
(distance-to-segment with a one-pixel smoothstep), so the edges are clean
without supersampling, and the whole thing is pure stdlib (zlib + struct).

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

# "K" as three capsules in unit coordinates (origin top-left, y down).
# Tuned so the junction reads as one letter rather than three sticks.
# x values are shifted ~0.027 left of the naive layout so the mark's painted
# extent (strokes + cap radius) is centred, not its centre-line.
_STROKES = [
    ((0.308, 0.235), (0.308, 0.765)),   # stem
    ((0.673, 0.235), (0.338, 0.505)),   # upper arm
    ((0.356, 0.487), (0.691, 0.765)),   # lower leg
]
_THICKNESS = 0.088   # capsule diameter in unit coords


def _distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Shortest distance from point p to segment ab."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    denom = abx * abx + aby * aby
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
    dx, dy = apx - t * abx, apy - t * aby
    return (dx * dx + dy * dy) ** 0.5


def _render(size: int, mark_scale: float) -> bytes:
    """Return raw RGB bytes for one icon.

    Args:
        size: Square edge length in pixels.
        mark_scale: Monogram size relative to the canvas. Below 1.0 shrinks
            the K toward the centre so a maskable crop cannot clip it.
    """
    half = 0.5
    radius = _THICKNESS / 2 * mark_scale
    # One pixel expressed in unit coords — the anti-aliasing ramp width.
    feather = 1.0 / size

    # Pre-scale the strokes around the canvas centre.
    strokes = [
        (
            (half + (ax - half) * mark_scale, half + (ay - half) * mark_scale),
            (half + (bx - half) * mark_scale, half + (by - half) * mark_scale),
        )
        for (ax, ay), (bx, by) in _STROKES
    ]

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter byte: None
        py = (y + 0.5) / size
        for x in range(size):
            px = (x + 0.5) / size
            distance = min(
                _distance_to_segment(px, py, ax, ay, bx, by)
                for (ax, ay), (bx, by) in strokes
            )
            # coverage: 1 inside the capsule, 0 outside, ramped across a pixel
            coverage = (radius + feather / 2 - distance) / feather
            coverage = 0.0 if coverage < 0.0 else (1.0 if coverage > 1.0 else coverage)
            for channel in range(3):
                value = MIDNIGHT[channel] + (PAPER[channel] - MIDNIGHT[channel]) * coverage
                rows.append(int(value + 0.5))
    return bytes(rows)


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
    # (filename, pixel size, monogram scale)
    #   maskable shrinks the mark into the 80% safe zone Android/iOS may crop.
    targets = [
        ("icon-192.png", 192, 1.0),
        ("icon-512.png", 512, 1.0),
        ("icon-512-maskable.png", 512, 0.72),
        ("apple-touch-icon.png", 180, 1.0),
    ]
    for filename, size, mark_scale in targets:
        raw = _render(size, mark_scale)
        path = OUTPUT_DIR / filename
        _write_png(path, size, raw)
        print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)} ({size}×{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
