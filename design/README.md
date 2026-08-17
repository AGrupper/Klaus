# Design assets

## klaus-icon-master.png

The master artwork for the Klaus app icon — a glowing tile "K" on a dark warm
ground (`#120e0b`), 1254×1254.

This is the source of truth. The PNGs in `frontend/public/` are derived from it
and should never be edited by hand.

### Regenerating the app icons

There is deliberately no generator script. The previous one
(`scripts/generate_app_icons.py`, removed 2026-08-17) drew the earlier
Conductor-style mark procedurally, and once the brand moved to raster artwork it
could only do harm — re-running it would have silently reverted the icons to the
old design.

Pillow is not a project dependency; install it ad hoc when you need to re-cut the
icons:

```bash
python3 -m venv /tmp/icontools && /tmp/icontools/bin/pip install Pillow
```

```python
from PIL import Image
im = Image.open("design/klaus-icon-master.png").convert("RGB")

# The master's glyph sits ~20px right of the canvas centre. Crop the largest
# square centred on the glyph's optical centre so the K lands dead-centre at
# every size, rather than inheriting the offset.
gcx, gcy = 647.0, 620.0
w, h = im.size
half = min(gcx, gcy, w - gcx, h - gcy)
sq = im.crop((round(gcx - half), round(gcy - half), round(gcx + half), round(gcy + half)))

for name, size in [
    ("icon-192-v2.png", 192),
    ("icon-512-v2.png", 512),
    ("icon-512-maskable-v2.png", 512),
    ("apple-touch-icon-v2.png", 180),
]:
    sq.resize((size, size), Image.LANCZOS).save(f"frontend/public/{name}", "PNG", optimize=True)
```

### Two constraints to preserve

**Maskable safe zone.** Android crops maskable icons to a circle inscribed in
the middle 80% of the canvas. In the current cut the glyph's furthest lit pixel
is at 71.8% of the half-canvas, so it clears the limit. If the artwork ever grows
within the frame, re-check before shipping.

**Cache-busting filenames.** iOS caches `apple-touch-icon` per-domain and will
not re-fetch a changed file at the same URL. Any future icon change must land on
a *new* filename (`-v3`, …) and update all four references together:
`frontend/index.html`, `frontend/vite.config.ts` (the PWA manifest block),
`frontend/src/sw.ts` (the push-notification icon), and the test in
`frontend/src/iconAssets.test.ts` that asserts the built output uses versioned
URLs.
