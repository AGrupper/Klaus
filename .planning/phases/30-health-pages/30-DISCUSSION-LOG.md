# Phase 30: Health Pages - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-06
**Phase:** 30-Health Pages
**Areas discussed:** Page structure & navigation, Time windows & history depth, Training history presentation, Nutrition trends & slot adherence, Sleep & recovery page (added at wrap-up)

---

## Page structure & navigation

| Option | Description | Selected |
|--------|-------------|----------|
| Segmented sub-tabs (Recommended) | Training / Nutrition / Sleep segmented control, landing on Training | ✓ |
| Overview dashboard first | Summary cards per domain, tap into full pages | |
| One long scrolling page | All three sections stacked with anchor jumps | |

**User's choice:** Segmented sub-tabs

| Option | Description | Selected |
|--------|-------------|----------|
| Remember last sub-tab (Recommended) | Reopens on the sub-tab last viewed | ✓ |
| Always land on Training | Deterministic landing | |

**User's choice:** Remember last sub-tab

| Option | Description | Selected |
|--------|-------------|----------|
| Keep the standard frame (Recommended) | Same center column as Today/Tasks; glance rail + collapsible chat stay | ✓ |
| Full-width charts | Drop the glance rail on Health pages | |
| You decide | Leave to UI phase | |

**User's choice:** Keep the standard frame

| Option | Description | Selected |
|--------|-------------|----------|
| Tap for values (Recommended) | Tooltips per point + range toggles; no zoom/pan | ✓ |
| Fully interactive | Pinch-zoom, pan, crosshair scrubbing | |
| Purely static | Charts as pictures, no tooltips | |

**User's choice:** Tap for values

---

## Time windows & history depth

| Option | Description | Selected |
|--------|-------------|----------|
| Preset toggles (Recommended) | 7d / 30d / 90d / 1y segmented control, consistent across pages | ✓ |
| Presets + custom picker | Adds free from/to date-range picker | |
| Scroll back through time | Backward pagination, no explicit range | |

**User's choice:** Preset toggles

| Option | Description | Selected |
|--------|-------------|----------|
| 30 days (Recommended) | Roughly a training-block month | ✓ |
| 7 days | Current week | |
| 90 days | Quarter view | |

**User's choice:** 30 days default

| Option | Description | Selected |
|--------|-------------|----------|
| 1 year, weekly points (Recommended) | Presets top out at 1y; >~90d aggregates weekly; 3y history stays chat-only | ✓ |
| Everything (All preset) | Full ~3-year Garmin backfill, monthly points | |
| 90 days max | Recent-focused only | |

**User's choice:** 1 year, weekly points

| Option | Description | Selected |
|--------|-------------|----------|
| Visible gaps (Recommended) | Missing days are breaks — never zero, never interpolated | ✓ |
| Connect across gaps | Bridge lines over missing days | |
| You decide | Per chart type, UI phase | |

**User's choice:** Visible gaps

---

## Training history presentation

| Option | Description | Selected |
|--------|-------------|----------|
| One mixed session log (Recommended) | Reverse-chronological stream, strength + runs interleaved with type badges | ✓ (modified) |
| Strength / Running split | Per-modality toggle with own trend charts | |
| Trends first, log second | Charts lead, list secondary | |

**User's choice:** Other (free text) — "Can we have one mixed session log but just have each training modality a different color or something?" → mixed log with per-modality color coding (exact colors → ui-phase).

| Option | Description | Selected |
|--------|-------------|----------|
| Full detail view (Recommended) | Per-set table (strength), lap/split table with pace+HR (runs), result vs previous (benchmarks) | ✓ |
| Expanded summary only | Richer card, no tables | |
| No drill-down | Skimming surface only | |

**User's choice:** Full detail view

| Option | Description | Selected |
|--------|-------------|----------|
| Volume + pace charts (Recommended) | Weekly strength volume + running pace/distance trend above the log | ✓ |
| Log only | No aggregate charts | |
| One combined load chart | Single mixed-modality load chart | |

**User's choice:** Volume + pace charts

| Option | Description | Selected |
|--------|-------------|----------|
| Both woven in (Recommended) | Block boundaries as labeled dividers + benchmarks as highlighted entries in the log | ✓ |
| Benchmarks section apart | Dedicated benchmarks strip, plain log | |
| Skip block context | No block framing on this page | |

**User's choice:** Both woven in

---

## Nutrition trends & slot adherence

| Option | Description | Selected |
|--------|-------------|----------|
| Slot-hit grid (Recommended) | Contribution-style grid: rows = fueling slots, columns = days, cells = logged/not | ✓ |
| Per-day slot count | Daily "4/6 slots hit" bar | |
| Slot macros over time | Per-slot macro averages | |

**User's choice:** Slot-hit grid

| Option | Description | Selected |
|--------|-------------|----------|
| Calories + macro toggle (Recommended) | One main daily chart, chip row switches series to protein/carbs/fat/fiber | ✓ |
| Small multiples | Five mini-charts at once | |
| Stacked macro bars | Composition bars + fiber mini-chart | |

**User's choice:** Calories + macro toggle

| Option | Description | Selected |
|--------|-------------|----------|
| Target line + averages (Recommended) | Target as reference line + range-average-vs-target summary incl. protein g/kg | ✓ |
| Averages only | Summary row only, no line | |
| No targets on this page | Pure observed data | |

**User's choice:** Target line + averages

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, day drill-down (Recommended) | Tap a bar/cell → that day's meals by slot with per-meal macros | ✓ |
| No drill-down | Trend altitude only | |

**User's choice:** Yes, day drill-down

---

## Sleep & recovery page (added at wrap-up)

At the "ready for context?" check, the user chose to also discuss the Sleep page rather than leave its composition to Claude's discretion.

| Option | Description | Selected |
|--------|-------------|----------|
| Three stacked charts (Recommended) | HRV, sleep (score + duration), body battery each get a compact chart | ✓ |
| Primary + toggle | One chart + metric chips (nutrition pattern) | |
| One combined chart | All metrics normalized on one multi-line chart | |

**User's choice:** Three stacked charts

| Option | Description | Selected |
|--------|-------------|----------|
| Both series overlaid (Recommended) | Overnight HRV daily + rolling 7-day baseline as second line | ✓ |
| Overnight only | Nightly values only | |
| Deviation from baseline | Difference around a zero line | |

**User's choice:** Both series overlaid

| Option | Description | Selected |
|--------|-------------|----------|
| Header stat row (Recommended) | Last night's HRV, sleep score, body battery, resting HR, readiness at top; no dedicated resting-HR/readiness charts | ✓ |
| Charts for everything | 4th/5th charts for resting HR + readiness | |
| Leave them off | Strictly HRV + sleep + body battery | |

**User's choice:** Header stat row

---

## Claude's Discretion

- Chart library choice (tooltips + light bundle + iOS-Safari constraints)
- Backend API shape + server-computed aggregates + weekly-bucket mechanics
- Postgres `daily_biometrics` wiring into a hub route (executor, no event-loop blocking)
- Strength "volume" metric definition (tonnage vs hard sets)
- Which fueling slots appear as grid rows
- Skeleton/loading/empty states
- All visual/layout/animation/color specifics → `/gsd:ui-phase 30`

## Deferred Ideas

- Custom date-range picker / arbitrary windows
- Surfacing the full ~3-year Garmin history in the hub (stays Klaus-chat)
- Fully interactive charts (zoom/pan/scrubbing)
- Overview/summary dashboard landing view
- Per-slot macro-depth adherence view (v2 of the nutrition page)
- Dedicated resting-HR / training-readiness trend charts
