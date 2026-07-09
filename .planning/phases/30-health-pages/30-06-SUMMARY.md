---
phase: 30-health-pages
plan: 06
subsystem: frontend
tags: [react, typescript, health-pages, nutrition, charts, slot-adherence, drilldown-sheet, vitest]

# Dependency graph
requires:
  - phase: 30-health-pages
    plan: 02
    provides: "GET /api/health/nutrition response contract (per-macro series, missing_dates, averages, targets, avg_protein_g_per_kg, slot_adherence)"
  - phase: 30-health-pages
    plan: 03
    provides: "Chart toolkit — LineChart/ChartCard/ChartEmptyState/ChartTooltip"
  - phase: 30-health-pages
    plan: 04
    provides: "useNutritionDetail(range) hook + RangeToggle control + NutritionMacroKey/NutritionDetailData types"
provides:
  - "frontend/src/components/health/nutrition/NutritionDetailPage.tsx — Nutrition sub-tab root: RangeToggle + MacroChipRow + MacroTrendChart + SlotAdherenceGrid + shared DayDrilldownSheet"
  - "frontend/src/components/health/nutrition/MacroChipRow.tsx — 5-way single-select macro chips (Calories default), each active chip in its OWN metric color"
  - "frontend/src/components/health/nutrition/MacroTrendChart.tsx — selected-metric LineChart + dashed target reference line + avg-vs-target summary row (protein appends g/kg)"
  - "frontend/src/components/health/nutrition/SlotAdherenceGrid.tsx — contribution-style hit/miss grid keyed on fueling-slot LABEL only (D-13)"
  - "frontend/src/components/health/nutrition/DayDrilldownSheet.tsx — per-slot day breakdown, slot labels only, never a clock time (D-16)"
affects: [30-08 HealthPage root composition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Macro color map (MACRO_COLORS: Calories #38BDF8 / Protein #F87171 / Carbs #FBBF24 / Fat #A78BFA / Fiber #2DD4BF) lives in MacroChipRow and is passed INTO the shared chart primitives as props — accent #6366F1 carve-out respected (nutrition chips never use accent)"
    - "SlotAdherenceGrid adapts habits/ContributionGrid CSS-grid convention (12px cells, 2px gap — named exception, NOT rounded to 4px; gridAutoFlow column; overflowX auto + scrollLeft=scrollWidth auto-scroll-to-newest) with rows=fueling-slot-labels, columns=days, 2-state hit/miss fill"
    - "Slot-label invariant (CLAUDE.md §6, D-13/D-16, T-30-06-01): grid aria-labels and drilldown rows render the fueling-slot NAME verbatim; a vitest asserts no HH:MM/clock-time string appears anywhere"
    - "Page holds one shared openDate state; both MacroTrendChart point taps and SlotAdherenceGrid cell taps open the single DayDrilldownSheet (D-16)"

key-files:
  created:
    - frontend/src/components/health/nutrition/MacroChipRow.tsx
    - frontend/src/components/health/nutrition/MacroTrendChart.tsx
    - frontend/src/components/health/nutrition/SlotAdherenceGrid.tsx
    - frontend/src/components/health/nutrition/DayDrilldownSheet.tsx
    - frontend/src/components/health/nutrition/SlotAdherenceGrid.test.tsx
    - frontend/src/components/health/nutrition/NutritionDetailPage.tsx
  modified: []

key-decisions:
  - "DayDrilldownSheet renders slots-hit + server-computed day macro totals rather than a per-meal macro breakdown: the /api/health/nutrition contract (30-02) exposes day-level totals + a slot-hit matrix but no per-slot macros. The sheet degrades gracefully (rows carry an optional `macros` field) so a future backend plan that adds per-slot macros renders the full UI-SPEC per-meal copy without a rewrite. No client-side re-derivation (T-30-06-02)."
  - "NutritionDetailPage reconstructs each day's DayMacros totals from the per-macro `series` (verbatim point lookups, null when the date is a gap) — no zero-filling (D-08)."
  - "Fiber target resolves from `targets.fiber_g_floor` (the other four macros map 1:1 onto their `targets` key); the floor is treated as the dashed reference line for the fiber metric."

patterns-established:
  - "Nutrition sub-page follows the 30-05 health-page composition shape: useState<RangeKey>('30d') + useState<NutritionMacroKey>('calories') → RangeToggle → useNutritionDetail(range) → Skeleton on isLoading / 'pull to refresh' copy on isError / content on data"

requirements-completed: [HLTH-02]

# Execution note
execution-note: "Task 1 (MacroChipRow + MacroTrendChart) and the Task 2 RED test were committed by the original wave-4 executor before a provider usage-limit interruption. Tasks 2 (GREEN) and 3 (NutritionDetailPage compose) were completed inline by the orchestrator on Opus 4.8 after the limit reset — same worktree, same branch, same commit conventions."
---

## What shipped

The Nutrition Detail sub-page (HLTH-02): a range toggle, a 5-way macro chip row
defaulting to Calories, a per-metric trend chart with a dashed target line and an
avg-vs-target summary (protein additionally shows g/kg bodyweight), and a
contribution-style fueling-slot adherence grid. Tapping any chart point or grid
cell opens a single shared day-drilldown sheet showing that day's slots and macro
totals — labeled by fueling-slot name, never a clock time.

## Slot-label invariant (D-13 / D-16 / CLAUDE.md §6)

The SlotAdherenceGrid and DayDrilldownSheet render fueling-slot LABELS only. The
canonical 08:00/12:00/20:00 slot timestamps are already stripped server-side; these
components never derive or display a clock time. `SlotAdherenceGrid.test.tsx` asserts
(a) cell aria-labels carry the slot name and (b) no `HH:MM` string appears in the
rendered grid or drilldown — 6/6 tests pass.

## Verification

- `npx tsc --noEmit` — clean (exit 0)
- `npx vitest run src/components/health/nutrition/SlotAdherenceGrid.test.tsx` — 6/6 pass
- Acceptance greps: per-metric colors present in MacroChipRow, no accent/#6366F1 leak,
  `g/kg`/`Target`/`Avg` summary present in MacroTrendChart, `2px` gap + `38BDF8`/`1F1F1F`
  hit/miss fills in SlotAdherenceGrid, no clock-time regex match in DayDrilldownSheet,
  all five wired components + "Fueling Slot Adherence" heading present in NutritionDetailPage.

## Commits

- `5abcad2` feat(30-06): add MacroChipRow + MacroTrendChart
- `f0b940d` test(30-06): add failing SlotAdherenceGrid slot-label invariant tests (RED)
- `b125b87` feat(30-06): add SlotAdherenceGrid + DayDrilldownSheet (slot-label invariant) (GREEN)
- `29882cc` feat(30-06): compose NutritionDetailPage (range + chip + trend + slot grid)

## Self-Check: PASSED

All three tasks executed, typecheck clean, slot-label invariant tests green, no new
dependencies. STATE.md/ROADMAP.md untouched (orchestrator owns post-wave writes).
