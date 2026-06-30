---
phase: 28-habits-supplements
reviewed: 2026-06-30T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - core/autonomous.py
  - core/proactive_alerts.py
  - core/tools.py
  - frontend/src/App.tsx
  - frontend/src/api/habits.ts
  - frontend/src/components/habits/ContributionGrid.tsx
  - frontend/src/components/habits/DoseEditSheet.tsx
  - frontend/src/components/habits/HabitCreateEditSheet.tsx
  - frontend/src/components/habits/HabitDetailView.tsx
  - frontend/src/components/habits/HabitRow.tsx
  - frontend/src/components/habits/HabitsPage.tsx
  - frontend/src/components/layout/GlanceRail.tsx
  - frontend/src/components/timeline/HabitsBand.tsx
  - frontend/src/components/timeline/TimelineDay.tsx
  - frontend/src/hooks/useHabits.ts
  - frontend/src/store/undoStore.ts
  - interfaces/web_server.py
  - memory/firestore_db.py
  - tests/test_autonomous.py
  - tests/test_habit_store.py
  - tests/test_habits_api.py
  - tests/test_proactive_alerts.py
  - tests/test_tools.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 28: Code Review Report

**Reviewed:** 2026-06-30
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

Phase 28 adds native habit/supplement tracking: a `HabitStore` + pure
`compute_streak_and_grid` in `memory/firestore_db.py`, nine `/api/habits/*`
routes, four-state contribution grid + streak UI, Today/GlanceRail integration,
and cross-domain links into the autonomous tick and proactive alerts.

Invariant compliance is good: every `/api/habits/*` route is gated on
`require_hub_session`; all sync Firestore calls run via `run_in_executor`; reads
pass through `_jsonsafe_doc`; completion dates are stored as plain ISO strings
(only `updated_at` is a SERVER_TIMESTAMP); responsive show/hide uses Tailwind
classes; the autonomous cost-gating order is preserved (habit adherence is a
free Layer-0 gather that wakes the free Layer-1 tick-brain, not the paid brain).
The streak/grid date math is date-only and DST-safe, and forward-only schedule
revisions resolve historical dates correctly.

No BLOCKER-class defects (no auth bypass, injection, crash, or data-loss path)
were found. Five WARNING-class correctness/robustness issues and four INFO items
are documented below. The most material are the unbounded `schedule_history`
growth on every edit (WR-01) and the orphaned soft-deleted habits with no
garbage collection (WR-02).

## Warnings

### WR-01: Every habit edit appends a redundant `schedule_history` revision

**File:** `frontend/src/components/habits/HabitCreateEditSheet.tsx:213-227`, `memory/firestore_db.py:3156-3163`
**Issue:** `HabitStore.update` appends a new `schedule_history` revision whenever
`"days"` is present in the patch (correct, forward-only D-19 behavior). But the
edit form's `handleSave` **always** includes `days: daysValue` in the edit
mutation payload — even when the user only changed the name, type, slot, or dose.
The backend therefore appends a new `{effective_from: today, days: <unchanged>}`
revision on *every* edit. Over time `schedule_history` grows without bound and
accumulates duplicate same-day revisions. (The backend route uses
`model_dump(exclude_unset=True)`, so the bloat is driven entirely by the
frontend always sending `days`.) Functionally streaks stay correct
(`_is_scheduled` picks the latest applicable revision), but the document bloats
and the revision history becomes meaningless.
**Fix:** Only send `days` when the schedule actually changed. Compute the
original days from the loaded habit and omit `days` from the edit payload when it
is unchanged:
```ts
const daysChanged = JSON.stringify(daysValue) !== JSON.stringify(originalDaysValue)
editHabit.mutate({
  name: name.trim(), type, dose: ..., slot,
  ...(daysChanged ? { days: daysValue } : {}),
}, { ... })
```

### WR-02: Soft-deleted habits become unrecoverable zombies when the user navigates away during the undo window

**Status: RESOLVED** (2026-06-30) — Added `HabitStore.reclaim_stale_deletions()` (option (a), read-time instead of cron): `list_active()` now best-effort hard-deletes any `status='completing'` doc whose `updated_at` is older than 120s (≫ the 4s undo window, so a legitimately-pending undo is never reclaimed). Missing-timestamp docs are treated as stale. The misleading UndoToast comment was corrected. Covered by 5 tests in `tests/test_habit_store.py::TestReclaimStaleDeletions`.

**File:** `frontend/src/components/tasks/UndoToast.tsx:123-129`, `memory/firestore_db.py:3171-3183`
**Issue:** `handleDelete` soft-deletes (status → `completing`), which removes the
habit from `list_active()` (and thus the entire UI). The hard-delete only fires
on the 4s timer expiry. The UndoToast cleanup deliberately does **not** fire
hard-delete on unmount ("user navigated away"). So if the user deletes a habit
and then navigates away (or closes the tab) before the timer fires, the habit is
left permanently in `status='completing'`: invisible (excluded by `list_active`),
never hard-deleted, and with no UI path to restore it (the undo toast is gone).
The code comment claims "server will garbage-collect orphaned 'completing' docs,"
but no such GC exists in the reviewed code. These docs accumulate forever.
**Fix:** Either (a) add a server-side sweep that hard-deletes `completing` habits
older than a threshold (cron), or (b) include `completing`-status habits in a
recovery surface, or (c) on UndoToast unmount, fire the pending hard-delete
instead of silently abandoning it. Update the misleading comment to match reality.

### WR-03: ContributionGrid rows do not align to weekdays and overflow the 52×7 layout

**File:** `frontend/src/components/habits/ContributionGrid.tsx:71-104`, `memory/firestore_db.py:3010-3026`
**Issue:** The grid is declared `gridTemplateColumns: repeat(52, 12px)` ×
`gridTemplateRows: repeat(7, 12px)` (364 slots) with `gridAutoFlow: column`, and
the component's docstring asserts "Mon=row1 … Sun=row7" with each column being
one calendar week. But the backend emits exactly **365** cells
(`window_days=365`, confirmed by `test_rolling_year_length`) starting at
`today - 364 days`, which is an arbitrary weekday — not a Monday. Consequences:
(1) the documented Mon→Sun row semantic is false (row N is not a fixed weekday),
so the GitHub-style week-column grouping the component is built for is broken;
(2) 365 cells exceed the 364 explicit slots, pushing a lone 53rd implicit column.
Per-cell aria-labels/colors remain correct, so this is visual/semantic, not data.
**Fix:** Have the backend pad the window to start on the most recent Monday on or
before `today - 364` (so the cell count is a multiple of 7 aligned to week
boundaries), or emit `not-scheduled`/empty leading cells to fill the first column
to the correct weekday offset, and size the grid columns to the actual week count.

### WR-04: Check-off does not invalidate the habit summary query — GlanceRail/Today counts go stale

**Status: RESOLVED** (2026-06-30) — `useCheckOffHabit.onSettled` now also invalidates `['habits','summary']` (matching `useSoftDeleteHabit`), so GlanceRail streak leaders and the pending count refetch after a check-off. Verified by `npx tsc --noEmit` + 82/82 vitest.


**File:** `frontend/src/hooks/useHabits.ts:151-154`
**Issue:** `useCheckOffHabit.onSettled` invalidates only `HABITS_QUERY_KEY`
(`['habits']`). It does not invalidate `['habits', 'summary']`. After a user
checks off a habit, `useHabitSummary()` (consumed by `GlanceRail` streak leaders
and the TIME-06 summary) keeps serving the pre-check-off `pending_today` count and
streaks until an unrelated refetch. `useSoftDeleteHabit` correctly invalidates
both keys, making the omission here inconsistent.
**Fix:** Invalidate the summary on check-off settle, matching the soft-delete hook:
```ts
onSettled: () => {
  queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
  queryClient.invalidateQueries({ queryKey: ['habits', 'summary'] })
},
```

### WR-05: `get_history` swallows the completions query failure and silently returns streak 0

**File:** `memory/firestore_db.py:3358-3378`
**Issue:** The inner `collection_group("records")` completions query is wrapped in
its own `try/except` that, on any failure, sets `completions = {}` and proceeds to
compute a streak from an empty set — returning `streak: 0` and an all-`missed`/
`pending` grid. This masks a real Firestore error (e.g. a transient outage or a
missing collection-group index) as legitimate "no completions," so the user sees
their streak silently reset to 0 rather than a load/error state. The outer
handler logs, but the inner swallow turns an infrastructure failure into wrong
data presented as truth.
**Fix:** Do not coerce a query failure into empty data. Let the inner exception
propagate to the outer `except`, which already returns the documented
`{"streak": 0, "grid": []}` sentinel — and have the API/UI treat an empty grid as
"could not load" rather than confidently rendering a zeroed streak. At minimum,
distinguish "query failed" from "no records" so the UI does not assert a 0 streak
on error.

## Info

### IN-01: Supplements cannot be un-checked from the UI

**File:** `frontend/src/components/habits/HabitRow.tsx:93-97`, `frontend/src/components/timeline/HabitsBand.tsx:129-133`
**Issue:** For `type === 'supplement'`, tapping the check button always opens
`DoseEditSheet`, whose `handleSave` always sends `done: true`. There is no path to
un-check a completed supplement (habits toggle, supplements do not). If a user
checks a supplement by mistake they cannot undo it from the row.
**Fix:** If the supplement is already `done_today`, toggle it off directly
(call `checkinHabit(..., done=false)`) instead of re-opening the dose sheet, or
add an "un-check" affordance inside the dose sheet.

### IN-02: Check-in route does not verify the habit is scheduled on the target date

**File:** `interfaces/web_server.py:2387-2434`, `memory/firestore_db.py:3228-3278`
**Issue:** `api_habit_checkin` only validates that `date` ∈ {today, yesterday}. It
does not check whether the habit is actually scheduled on that date.
`log_completion` writes a record regardless, but `compute_streak_and_grid` marks
non-scheduled days as `not-scheduled` and ignores the completion — producing an
orphan completion doc that is invisible in the grid and streak.
**Fix:** Either reject check-ins for non-scheduled dates (400), or document that
off-schedule completions are intentionally inert. Low impact at personal scale.

### IN-03: `_handle_get_habit_adherence` shadows the builtin `type`

**File:** `core/tools.py:2558-2575`
**Issue:** The handler parameter is named `type`, shadowing the builtin within the
function. It is only used as a filter string so there is no functional bug, but it
is a readability/lint smell and mirrors the LLM tool-arg key.
**Fix:** Rename to `habit_type` (and map the schema arg accordingly) for clarity.

### IN-04: `streak_leaders` lists 0-streak habits as "leaders"

**File:** `memory/firestore_db.py:3395-3408`
**Issue:** `get_summary` builds `streak_leaders` from *all* active habits sorted by
descending streak and slices the top 4 — including habits whose streak is 0. The
GlanceRail then renders them with "No streak," which is odd for a "streak leaders"
card when no habit has a streak.
**Fix:** Filter to `streak > 0` before slicing, or render the empty state when no
leader has a positive streak.

---

_Reviewed: 2026-06-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
