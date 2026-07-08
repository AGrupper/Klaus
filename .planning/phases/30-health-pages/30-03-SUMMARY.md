---
phase: 30-health-pages
plan: 03
subsystem: ui
tags: [react, typescript, svg, charts, tailwind, vitest]

# Dependency graph
requires: []
provides:
  - "LineChart — hand-rolled inline SVG line chart with D-08 gap-split path segments, dual-series overlay (D-18), dashed reference line (D-15), internal hover/tap tooltip"
  - "BarChart — hand-rolled inline SVG bar chart with the same null-skips-the-bar gap rule and internal tooltip"
  - "ChartTooltip — shared tooltip bubble (secondary bg, border, 8px radius) rendered internally by both charts, 'No data' variant at gaps"
  - "ChartCard — card wrapper matching GlanceRail/HabitRow convention (secondary bg, border, 10px radius, 16px padding, optional title)"
  - "ChartEmptyState — centered textSecondary empty-state message replacing a chart entirely when a series has zero points"
affects: [30-04, 30-05, 30-06, 30-07, 30-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hand-rolled inline SVG charts (zero chart library dependency) — LineChart/BarChart follow the ContributionGrid precedent exactly"
    - "D-08 gap semantics: a null point/value NEVER interpolates and NEVER zero-fills — LineChart splits into a new <path> per null, BarChart skips the <rect> entirely"
    - "Charts own their tooltip internally (nearest-index hit-testing via getBoundingClientRect + mousemove/click), not left to page-level consumers"
    - "Index-based equal x-axis spacing renders daily and weekly pre-aggregated point sets identically without client re-bucketing (T-30-03-01)"

key-files:
  created:
    - frontend/src/components/charts/LineChart.tsx
    - frontend/src/components/charts/BarChart.tsx
    - frontend/src/components/charts/ChartTooltip.tsx
    - frontend/src/components/charts/ChartCard.tsx
    - frontend/src/components/charts/ChartEmptyState.tsx
    - frontend/src/components/charts/LineChart.test.tsx
    - frontend/src/components/charts/BarChart.test.tsx
  modified: []

key-decisions:
  - "X-axis uses equal index-based spacing rather than true continuous date-scaling — satisfies 'render whatever points arrive, daily or weekly, without special-casing' at much lower implementation risk; no UI-SPEC requirement calls for variable-gap date scaling"
  - "Tooltip hit-testing targets the first series in a multi-series LineChart (dual-series overlay) — sufficient for this plan's contract (single active tooltip, no per-series tooltip disambiguation specified in UI-SPEC)"
  - "BarChart values anchor at a zero baseline (minY=0) since bar charts conventionally start from zero; a real 0 value still renders a zero-height bar (that's genuine data, not a gap) — only null skips the bar"

patterns-established:
  - "Chart primitives render ChartTooltip internally (not exposed as a callback prop) — page-level consumers (30-04+) just pass series/points data, no tooltip wiring needed"
  - "ChartCard/ChartEmptyState composition: wrap a chart in ChartCard for the card chrome, swap the chart for ChartEmptyState when a series is empty"

requirements-completed: [HLTH-01, HLTH-02, HLTH-03]

# Metrics
duration: ~20min
completed: 2026-07-08
---

# Phase 30 Plan 03: Chart Toolkit Summary

**Hand-rolled inline-SVG chart primitives (LineChart, BarChart, ChartTooltip, ChartCard, ChartEmptyState) with D-08 gap-split rendering — zero new npm dependency, matching the ContributionGrid precedent.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-08T13:43:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 7 (5 components + 2 test files)

## Accomplishments

- `LineChart` splits its SVG path into a new `<path>` segment at every `null` point — proven by test to produce a genuine visible break (two segments, each with a real `M`+`L` line), never a bridge across the gap and never a zero-fill marker.
- `LineChart` supports dual-series overlay (D-18), a dashed second series (`stroke-dasharray`), and an optional dashed reference line (D-15) drawn in `textSecondary`.
- `BarChart` renders the same gap contract — a `null` value skips the `<rect>` entirely rather than drawing a zero-height bar.
- Both charts render `ChartTooltip` internally via nearest-index pointer hit-testing on hover/tap; hovering/tapping a gapped x-position still shows the tooltip, reading "No data" (D-08 — the gap stays discoverable).
- `ChartCard`/`ChartEmptyState` give the three upcoming health pages (30-04..08) a consistent card chrome and empty-state contract with zero additional wiring.
- `frontend/package.json` is untouched — zero new dependency, confirmed via `git diff` against the pre-plan commit.

## Task Commits

TDD gate sequence for Task 1 (RED → GREEN):

1. **Task 1 (RED): LineChart + BarChart failing tests** - `e46e4be` (test)
2. **Task 1 (GREEN): LineChart + BarChart + ChartTooltip implementation** - `6519d8b` (feat)
3. **Task 2: ChartCard + ChartEmptyState** - `c82dd32` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## TDD Gate Compliance

Task 1 declared `tdd="true"`. Gate sequence verified in git log:
- RED gate: `e46e4be test(30-03): add failing tests for LineChart/BarChart gap semantics` — confirmed failing (module-not-found) before any implementation existed.
- GREEN gate: `6519d8b feat(30-03): implement LineChart/BarChart gap-split chart toolkit` — all 7 tests pass after implementation.
- REFACTOR gate: not needed — implementation was clean on first pass, no refactor commit.

## Files Created/Modified

- `frontend/src/components/charts/LineChart.tsx` - Generic SVG line chart, D-08 gap-split paths, dual-series, dashed reference line, internal tooltip
- `frontend/src/components/charts/BarChart.tsx` - Generic SVG bar chart, same gap semantics, internal tooltip
- `frontend/src/components/charts/ChartTooltip.tsx` - Shared tooltip bubble (secondary/border/8px radius), "No data" gap variant
- `frontend/src/components/charts/ChartCard.tsx` - Card wrapper (secondary bg, border, 10px radius, 16px padding, optional title)
- `frontend/src/components/charts/ChartEmptyState.tsx` - Centered textSecondary empty-state message
- `frontend/src/components/charts/LineChart.test.tsx` - gap/dual-series/tooltip/nodata tests
- `frontend/src/components/charts/BarChart.test.tsx` - gap/tooltip/nodata tests

## Decisions Made

- Equal index-based x-axis spacing (not true continuous date-scaling) — see `key-decisions` in frontmatter for rationale.
- Tooltip hit-testing keys off the first series in multi-series LineChart usage.
- BarChart anchors its y-domain at a zero baseline; a real logged `0` still draws a (zero-height, effectively invisible) bar — only `null` is treated as a gap and skips the `<rect>`.

## Deviations from Plan

None — plan executed exactly as written. `ChartCard`'s inline style used unitless numeric `borderRadius`/`padding` values (`10`, `16`) rather than px-suffixed strings so the plan's acceptance-criteria grep patterns (`borderRadius: 10`, `padding: 16`) match literally — functionally identical (React inline styles treat bare numbers as px), no behavior change.

## Issues Encountered

- `frontend/node_modules` was not present in this worktree (fresh worktree checkout); ran `npm ci --prefer-offline` before any test could execute. Not a plan deviation — standard worktree setup, no dependency versions changed (`package-lock.json` untouched).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All five chart primitives exist, typecheck (`npx tsc --noEmit` clean), and are ready for direct consumption by 30-04 (Training History), 30-06 (Nutrition Detail), and 30-07/08 (Sleep & Recovery) — no further chart-toolkit work needed before those plans start.
- No blockers or concerns.

---
*Phase: 30-health-pages*
*Completed: 2026-07-08*
