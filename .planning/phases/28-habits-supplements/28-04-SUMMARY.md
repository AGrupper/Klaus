---
phase: 28-habits-supplements
plan: "04"
subsystem: frontend-habits
tags: [habits-ui, contribution-grid, ios-sheets, optimistic-mutations, react-query, zustand]
dependency_graph:
  requires: [/api/habits/*, useHabits, undoStore, UndoToast, useVisualViewport, TaskDetailSheet-pattern]
  provides: [HabitsPage, HabitRow, HabitCreateEditSheet, DoseEditSheet, HabitDetailView, ContributionGrid]
  affects: [frontend/src/App.tsx, frontend/src/components/habits/*, frontend/src/store/undoStore.ts]
tech_stack:
  added: []
  patterns:
    - react-query optimistic mutation (onMutate/onError/onSettled)
    - zustand UndoItem with resourceType discriminator
    - iOS bottom-sheet (z:190 scrim / z:191 sheet, useVisualViewport keyboard, scroll-lock)
    - pure-CSS 52×7 contribution grid (display:grid, gridAutoFlow:column, gap:2px)
key_files:
  created:
    - frontend/src/components/habits/HabitRow.tsx
    - frontend/src/components/habits/HabitCreateEditSheet.tsx
    - frontend/src/components/habits/DoseEditSheet.tsx
    - frontend/src/components/habits/HabitsPage.tsx
    - frontend/src/components/habits/ContributionGrid.tsx
    - frontend/src/components/habits/HabitDetailView.tsx
  modified:
    - frontend/src/App.tsx
    - frontend/src/store/undoStore.ts  (Task 1 — previous executor)
    - frontend/src/api/habits.ts       (Task 1 — previous executor)
    - frontend/src/hooks/useHabits.ts  (Task 1 — previous executor)
decisions:
  - "gridAutoFlow:column added to ContributionGrid so each column = one calendar week (Mon–Sun); PATTERNS.md template omitted this detail"
  - "CELL_COLORS exported from ContributionGrid.tsx so HabitDetailView legend reuses same fills without re-declaring"
  - "HabitsPage wires HabitDetailView at Task 3 level (single file touched once rather than placeholder→real in two commits) since Task 2 files were never committed by prior session"
  - "Kebab Edit→HabitCreateEditSheet directly; body tap→HabitDetailView (which has its own Edit footer); both paths are distinct to reduce tap confusion"
requirements-completed: [HABIT-01, HABIT-02, HABIT-04]
metrics:
  duration: "~35 minutes (continuation session)"
  completed: "2026-06-30"
  tasks_completed: 2
  files_changed: 7
---

# Phase 28 Plan 04: Habits Tab Frontend Summary

**One-liner:** Full Habits tab UI — slot-grouped list with optimistic check-off toggle, iOS-safe bottom sheets (create/edit/dose/detail), and a pure-CSS 52×7 four-state ContributionGrid wired to the per-habit history endpoint.

## Context

This plan was executed as a **cross-session continuation**. Task 1 (data layer: api/habits.ts, useHabits.ts, undoStore extension) was committed in a prior session (commit ec768aa). This session completed Tasks 2 and 3.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Data layer (prior session) | ec768aa | api/habits.ts, useHabits.ts, undoStore.ts |
| 2 | HabitsPage + HabitRow + sheets + /habits route | a3ca72b | HabitsPage, HabitRow, HabitCreateEditSheet, DoseEditSheet, App.tsx |
| 3 | ContributionGrid + HabitDetailView | a771a1d | ContributionGrid.tsx, HabitDetailView.tsx |

## What Was Built

### Task 2: Habits list UI + sheets

**`HabitsPage.tsx`** (`frontend/src/components/habits/HabitsPage.tsx`)
- Slot-grouped list: Morning → Noon → Evening → Bedtime, sticky group headers (`#0A0A0A` bg to prevent scroll bleed)
- Loading / error / empty states with 28-UI-SPEC exact copywriting ("No habits yet" / "Add your first habit or supplement to start tracking.")
- Phone FAB: `56px` accent, `aria-label="Add habit"`, `bottom: calc(env(safe-area-inset-bottom, 0px) + 76px)`, wrapped in `<div className="md:hidden">` (Tailwind class, never inline display)
- State management: `editOpen/editHabit`, `doseOpen/doseHabit`, `detailOpen/detailHabit`
- Delete flow: `softDeleteMutation` → `undoShow({ resourceType: 'habit' })` → UndoToast 4s → `hardDeleteHabit`

**`HabitRow.tsx`** (`frontend/src/components/habits/HabitRow.tsx`)
- 44px touch-target check button: accent circle fill + checkmark when done, open circle when pending, 150ms `ease-out` transition
- Habit type: immediate `useCheckOffHabit` toggle; supplement type: tap → `DoseEditSheet` (via `onOpenDose`)
- Body tap → `HabitDetailView` (via `onOpenDetail`)
- `SlotChip` (`#2A2A2A` bg, 3px 8px padding, radius 6px) + streak count inline
- Dose label (supplement only, Label 13px textSecondary)
- Kebab `aria-label="Habit options"` with Edit (→ `HabitCreateEditSheet`) and Delete (`color: destructive #EF4444`)

**`HabitCreateEditSheet.tsx`** (`frontend/src/components/habits/HabitCreateEditSheet.tsx`)
- iOS sheet: scrim `z:190`, sheet `z:191` (beats BottomTabs `z:100`)
- `useVisualViewport` keyboardInset; `document.body.style.overflow='hidden'` scroll-lock; no phone `autoFocus`
- `onMouseDown={e=>e.preventDefault()}` on Cancel + scrim (blur-before-click trap)
- Fields: Name, Type segmented (Habit/Supplement), Dose (supplement only), Schedule day chips S M T W T F S, Slot segmented (Morning/Noon/Evening/Bedtime)
- Day selection: `Set<number>` (Mon=0, Sun=6); `'daily'` when all 7 selected; ≥1 required
- CTA: "Add habit" (create) / "Save changes" (edit) via `useCreateHabit` / `useEditHabit`

**`DoseEditSheet.tsx`** (`frontend/src/components/habits/DoseEditSheet.tsx`)
- `z:192` phone / `z:202` desktop (above HabitDetailView / HabitCreateEditSheet)
- Prefills default dose from `habit.dose`; fires `checkinHabit(id, today, true, doseTaken)` on "Save dose"
- "Discard dose" has `onMouseDown` preventDefault and makes no state change
- All iOS traps applied: useVisualViewport, scroll-lock, no phone autoFocus

**`App.tsx`**
- Imports `HabitsPage` from `./components/habits/HabitsPage`; `ComingSoon label="Habits"` replaced with real component

### Task 3: ContributionGrid + HabitDetailView

**`ContributionGrid.tsx`** (`frontend/src/components/habits/ContributionGrid.tsx`)
- Pure CSS: `display:grid`, `gridTemplateColumns: repeat(52, 12px)`, `gridTemplateRows: repeat(7, 12px)`, `gridAutoFlow: column` (so each column = 1 calendar week, Mon–Sun top-to-bottom), `gap: 2px` (named exception)
- `role="grid"` container; each cell `role="gridcell"` + `aria-label="{date}: {state}"`
- `CELL_COLORS` map: `done: accent`, `missed: '#3A1A1A'` (only hardcoded hex), `not-scheduled: skeleton`, `pending: border`
- `CELL_COLORS` exported for reuse in `HabitDetailView` legend

**`HabitDetailView.tsx`** (`frontend/src/components/habits/HabitDetailView.tsx`)
- Phone bottom sheet (z:190 scrim / z:191 sheet, 250ms slide-up); desktop centered modal (max-width 480px)
- Consumes `useHabitHistory(id)` → feeds `cells` to `ContributionGrid`
- Renders: habit name (Heading 20px/600), SlotChip + streak, dose (supplement only), "HISTORY" label (uppercase 0.04em), ContributionGrid, four-state legend with `CELL_COLORS` swatches, streak label ("N-day streak" / "No streak — check off today to start one.")
- Footer: "Edit" (accent 44px → `onClose()` + `onEdit(habit)`) + "Delete habit" (`destructive`, `onMouseDown` preventDefault)
- `HabitsPage` replaces placeholder div with `<HabitDetailView ...>`

## Verification Results

- `npx tsc --noEmit`: zero errors
- `npx vitest run`: 82/82 tests pass (no regressions)
- `npx vite build`: SPA bundle built successfully
- `grep -rn "dangerouslySetInnerHTML" frontend/src/components/habits/`: zero hits (T-28-xss)
- `grep -rn "style={{ *display" frontend/src/components/habits/`: all hits are layout `display:flex` inside class-driven wrappers — no responsive show/hide via inline style (T-28-display)
- `grep -rn "react-calendar-heatmap\|recharts\|chart" frontend/src/components/habits/`: zero hits (no chart library)
- Z-index chain confirmed: scrim 190, sheet 191, DoseEditSheet 192 (literals present)
- `gridTemplateColumns: 'repeat(52, 12px)'`: confirmed in ContributionGrid.tsx
- Concurrent-session files (core/tools.py, mcp_tools/calendar_tool.py, prompts/smart_agent.md, tests/test_calendar_tool.py, tests/test_tools.py): NOT staged or committed

## Deviations from Plan

### Auto-applied (Rule 1 / Rule 2)

**1. [Rule 2 - Missing] Added `gridAutoFlow: 'column'` to ContributionGrid**
- **Found during:** Task 3 analysis
- **Issue:** PATTERNS.md template omitted `grid-auto-flow: column`. Without it, cells fill row-by-row, making each row a week instead of each column — visually incorrect for a GitHub-style contribution grid (UI-SPEC: "52 columns = weeks, 7 rows = Mon–Sun")
- **Fix:** Added `gridAutoFlow: 'column'` to the grid container style
- **Files modified:** `frontend/src/components/habits/ContributionGrid.tsx`
- **Commit:** a771a1d

**2. [Rule 2 - Missing] Exported `CELL_COLORS` from ContributionGrid.tsx**
- **Found during:** Task 3 — HabitDetailView legend needs the same four-state fills
- **Issue:** Plan mentions importing the colors for the legend but doesn't specify where they live
- **Fix:** Exported `CELL_COLORS` from ContributionGrid.tsx; HabitDetailView imports it
- **Files modified:** `frontend/src/components/habits/ContributionGrid.tsx`, `HabitDetailView.tsx`
- **Commit:** a771a1d

### Cross-session continuity

This was a continuation execution. The prior session committed Task 1 (ec768aa) and left Tasks 2 and 3 uncommitted on disk. This session:
1. Reviewed all 5 pre-existing uncommitted files (HabitsPage, HabitRow, HabitCreateEditSheet, DoseEditSheet, App.tsx) — all were complete and correct
2. Created the 2 missing files (ContributionGrid, HabitDetailView)
3. Updated HabitsPage to replace the Task-3 placeholder with the real HabitDetailView
4. Committed Task 2 (a3ca72b) then Task 3 (a771a1d)

## Known Stubs

None. All components connect to real API hooks (`useHabits`, `useHabitHistory`, `useCreateHabit`, `useEditHabit`, `useCheckOffHabit`, `useSoftDeleteHabit`). No hardcoded or placeholder data flows to UI rendering.

## Threat Flags

No new threat surface beyond the plan's threat model. Verified:
- T-28-xss: zero `dangerouslySetInnerHTML` in habits folder
- T-28-display: all responsive visibility via Tailwind classes; no inline `style={{display}}`
- T-28-iossheet: z:190/191 chain, useVisualViewport, scroll-lock, onMouseDown preventDefault
- T-28-auth: all data goes through `useHabits` / `useCheckOffHabit` which call `apiFetch` (session cookie, no manual token handling)
- T-28-SC: no new npm packages installed

## Self-Check: PASSED

- `frontend/src/components/habits/ContributionGrid.tsx` exists: YES
- `frontend/src/components/habits/HabitDetailView.tsx` exists: YES
- `frontend/src/components/habits/HabitsPage.tsx` exists: YES (HabitDetailView imported and wired)
- `frontend/src/components/habits/HabitRow.tsx` exists: YES
- `frontend/src/components/habits/HabitCreateEditSheet.tsx` exists: YES
- `frontend/src/components/habits/DoseEditSheet.tsx` exists: YES
- Commit ec768aa (Task 1, prior session) exists: YES
- Commit a3ca72b (Task 2) exists: YES
- Commit a771a1d (Task 3) exists: YES
- `npx tsc --noEmit`: PASS
- `npx vitest run`: 82/82 PASS
- `npx vite build`: PASS
- Concurrent-session files untouched: CONFIRMED
