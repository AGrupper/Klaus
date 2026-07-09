---
phase: 28-habits-supplements
plan: "05"
subsystem: frontend-timeline-rail
tags: [habits-ui, timeline-band, glance-rail, react-query, optimistic-mutations, responsive-display]
dependency_graph:
  requires: [useHabits, useCheckOffHabit, useHabitSummary, DoseEditSheet, DueTasksBand-pattern]
  provides: [HabitsBand, TimelineDay-HabitsBand-mount, GlanceRail-Habits-card]
  affects:
    - frontend/src/components/timeline/HabitsBand.tsx
    - frontend/src/components/timeline/TimelineDay.tsx
    - frontend/src/components/layout/GlanceRail.tsx
    - frontend/src/components/timeline/TimelineDay.test.tsx
tech_stack:
  added: []
  patterns:
    - DueTasksBand mirror (band header: accent 4px×32px stripe, 10px 14px 6px padding named exception)
    - useHabits() client-side scheduled_today filter + slot sort
    - DoseEditSheet lift-state (doseHabit/doseOpen at HabitsBand level)
    - GlanceRail Tasks-card copy pattern (navigate/aria-label/heading/rows/empty)
    - 13px/600 compact-metric streak value (NOT 14px — UI-SPEC line 71)
key_files:
  created:
    - frontend/src/components/timeline/HabitsBand.tsx
  modified:
    - frontend/src/components/timeline/TimelineDay.tsx
    - frontend/src/components/layout/GlanceRail.tsx
    - frontend/src/components/timeline/TimelineDay.test.tsx
decisions:
  - "HabitsBand uses useHabits() client-side filter (scheduled_today===true) rather than a separate endpoint — mirrors DueTasksBand pattern; no new API calls"
  - "DoseEditSheet mounted at HabitsBand level with doseHabit/doseOpen state; supplements always open the sheet on tap (consistent with HabitRow in HabitsPage)"
  - "Streak value in GlanceRail uses typography.label.fontSize (13px) + fontWeight 600 — not the Tasks-card 14px literal which violates the token scale"
  - "useHabits mock added to TimelineDay.test.tsx (Rule 1 auto-fix) to match existing DueTasksBand mock pattern and restore 8/8 pass baseline"
requirements-completed: [HABIT-02, TIME-06]
metrics:
  duration: "~20 minutes"
  completed: "2026-06-30"
  tasks_completed: 2
  files_changed: 4
---

# Phase 28 Plan 05: Today Timeline Habits Band + GlanceRail Streaks Card Summary

**One-liner:** HabitsBand on the Today timeline (slot-grouped, one-tap toggle + DoseEditSheet for supplements) and a Habits streaks card in the desktop GlanceRail, both driven by Plan-04 hooks with class-only responsive display.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | HabitsBand.tsx + mount in TimelineDay.tsx | c13fa6b | HabitsBand.tsx (new), TimelineDay.tsx, TimelineDay.test.tsx |
| 2 | GlanceRail Habits streaks card (desktop) | 5b5b736 | GlanceRail.tsx |

## What Was Built

### Task 1: HabitsBand.tsx + TimelineDay mount

**`HabitsBand.tsx`** (`frontend/src/components/timeline/HabitsBand.tsx`)
- `useHabits()` data source — filters client-side to `scheduled_today === true`
- Slot sort: Morning → Noon → Evening → Bedtime → "any time" (slotRank helper)
- Guard: `if (scheduledToday.length === 0) return null` — no empty placeholder, matches DueTasksBand (line ~236)
- Section header: "Habits" label, accent `#6366F1` left-border stripe (4px × 32px), padding `10px 14px 6px` — copy-exact of DueTasksBand header; band-header named exception (UI-SPEC Spacing line 54)
- Per row (`HabitsBandRow`): 44px CheckButton (filled accent `CheckCircle2` when done, open `Circle` when pending, 150ms `color` transition), habit name (Body 16px, plain React text — NOT a link; no `useNavigate`), `DosePill` for supplements (Label 13px, border background), `SlotChip`
- Tap habit → immediate `useCheckOffHabit` toggle (`done: !done_today`, D-07)
- Tap supplement → opens `DoseEditSheet` (D-09) via lifted `doseHabit`/`doseOpen` state at band level
- `DoseEditSheet` mounted at band level (outside the row loop) to avoid z-index nesting issues
- Colors imported from `tokens.ts` (`accent`, `border`, `textPrimary`, `textSecondary`, `typography`, `fontFamily`) — no hardcoded hex
- No `dangerouslySetInnerHTML`; no `style={{ display }}` responsive override (T-28-xss, T-28-display)

**`TimelineDay.tsx`**
- Added `import { HabitsBand } from './HabitsBand'`
- `<HabitsBand />` mounted in Section 3.6, immediately after `<DueTasksBand />` (comment label `{/* Section 3.5 */}`) and before timed calendar events — matches UI-SPEC render order

**`TimelineDay.test.tsx`** (Rule 1 auto-fix)
- Added `vi.mock('../../hooks/useHabits', ...)` mirroring the existing `useTasks`/`useTaskSummary` mocks
- Returns empty list → `HabitsBand` guard fires → renders nothing → test environment clean
- All 8 existing tests restored to pass (baseline preserved)

### Task 2: GlanceRail Habits streaks card

**`GlanceRail.tsx`** (`frontend/src/components/layout/GlanceRail.tsx`)
- Added imports: `useHabitSummary` from `hooks/useHabits`; `textPrimary`, `textSecondary`, `typography` from `tokens`
- `const { data: habitSummary } = useHabitSummary()` — react-query deduplicates alongside any other consumer
- `streakLeaders = (habitSummary?.streak_leaders ?? []).slice(0, 4)` — max 4 rows per UI-SPEC
- Habits card positioned after the Tasks card (before `</aside>`) — inside the existing `hidden md:flex md:flex-col` rail wrapper; no new inline `display` added (T-28-display)
- Card structure mirrors Tasks card: `role="button"`, `tabIndex={0}`, `onClick(() => navigate('/habits'))`, `onKeyDown` Enter/Space handler, `aria-label="Habits overview — navigate to habits"`
- Heading "Habits" at `typography.heading.fontSize` (20px) / `fontWeight: 600` / `textPrimary`
- Streak leader rows: label = habit name at `typography.label.fontSize` (13px) / `typography.label.fontWeight` (400) / `textSecondary`; value = "[N]-day streak" at `typography.label.fontSize` (13px) / `fontWeight: 600` / `textPrimary` — explicitly avoids the Tasks-card 14px literal which is not a declared token (UI-SPEC Typography line 71)
- `leader.streak > 0 ? `${leader.streak}-day streak` : 'No streak'` (copywriting per UI-SPEC)
- Empty state: "No habits defined." at Label 13px textSecondary (when `streak_leaders` is empty)
- Habit names rendered as plain React text (T-28-xss: no `dangerouslySetInnerHTML`)

## Deviations from Plan

### Auto-applied (Rule 1 auto-fix)

**1. [Rule 1 - Bug] Added `useHabits` mock to `TimelineDay.test.tsx`**
- **Found during:** Task 1 verification — `npx vitest run src/components/timeline` failed with 6 failures
- **Issue:** `HabitsBand` calls `useHabits()` (react-query `useQuery`), which requires a `QueryClientProvider`. The test renders `TimelineDay` without one. The same issue existed for `DueTasksBand` and was solved with `vi.mock('../../hooks/useTasks', ...)` and `vi.mock('../../hooks/useTaskSummary', ...)`. `HabitsBand` needed the same treatment.
- **Fix:** Added `vi.mock('../../hooks/useHabits', ...)` returning empty array + stub mutate functions — matches the existing mock pattern exactly
- **Files modified:** `frontend/src/components/timeline/TimelineDay.test.tsx`
- **Commit:** c13fa6b

## Known Stubs

None. Both `HabitsBand` and the GlanceRail Habits card connect to real API hooks (`useHabits`, `useHabitSummary`, `useCheckOffHabit` via `DoseEditSheet`). No hardcoded or placeholder data flows to UI rendering.

## Threat Flags

No new threat surface beyond the plan's threat model. Verified:
- T-28-xss: `grep -rn "dangerouslySetInnerHTML" frontend/src/components/timeline/HabitsBand.tsx frontend/src/components/layout/GlanceRail.tsx` → zero hits; habit name + dose rendered as plain React children
- T-28-display: `grep -rn "style={{ *display" frontend/src/components/timeline/HabitsBand.tsx` → zero hits; band visibility inherits TimelineDay layout; rail card visibility driven by existing `hidden md:flex` wrapper class
- T-28-auth: all data goes through `useHabits` / `useHabitSummary` → `apiFetch` (session cookie); no manual token handling
- T-28-SC: no new npm packages installed

## Self-Check: PASSED

- `frontend/src/components/timeline/HabitsBand.tsx` exists: YES
- `frontend/src/components/timeline/TimelineDay.tsx` contains "HabitsBand": YES
- `frontend/src/components/layout/GlanceRail.tsx` contains "useHabitSummary": YES
- `frontend/src/components/layout/GlanceRail.tsx` contains "/habits": YES
- `grep -rn "style={{ *display" frontend/src/components/timeline/HabitsBand.tsx` → zero hits: YES
- `grep -rn "dangerouslySetInnerHTML"` in both files → zero hits: YES
- Commit c13fa6b (Task 1) exists: YES
- Commit 5b5b736 (Task 2) exists: YES
- `npx tsc --noEmit`: PASS (zero errors)
- `npx vitest run`: 82/82 PASS
- `npx vite build`: PASS (PWA bundle built clean)
