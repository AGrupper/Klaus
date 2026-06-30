---
phase: 28-habits-supplements
plan: "01"
subsystem: backend-store
tags: [habit-store, streak, firestore, tdd, dst]
dependency_graph:
  requires: []
  provides: [HabitStore, compute_streak_and_grid, _is_scheduled]
  affects: [memory/firestore_db.py, tests/test_habit_store.py]
tech_stack:
  added: []
  patterns: [TaskStore-CRUD, MealStore-subcollection, _jsonsafe_doc, TDD-RED-GREEN]
key_files:
  created:
    - tests/test_habit_store.py
  modified:
    - memory/firestore_db.py
decisions:
  - "schedule_history is append-only (D-19): update() reads, appends new revision, writes back — never mutates prior revisions"
  - "compute_streak_and_grid is pure module-level (no self, no Firestore) — called from tests with bare datetime.date"
  - "Completion path is habit_completions/{date}/records/{habit_id} mirroring MealStore subcollection pattern"
  - "H-28-IV invariant: all date fields are plain strings; only updated_at uses SERVER_TIMESTAMP"
  - "_FakeRecordsCol.stream() sets doc.id = hid (dict key) not data['id'] — completion records key by habit_id not 'id'"
  - "DST test fixture: date(2026,6,29) used instead of date(2026,6,30) for Monday — June 30 is Tuesday (weekday=1)"
metrics:
  duration: "~35 minutes"
  completed: "2026-06-30"
  tasks_completed: 2
  files_changed: 2
---

# Phase 28 Plan 01: HabitStore + compute_streak_and_grid Summary

**One-liner:** Firestore HabitStore with two-collection design (definitions + date-partitioned completions) plus pure `compute_streak_and_grid` function covering four-state grid, DST-safe date arithmetic, and forward-only effective-dated schedules.

## Tasks Completed

| # | Task | Commit | Status |
|---|------|--------|--------|
| 1 | Wave-0 test scaffold (RED) | a5ff26d | Done |
| 2 | HabitStore + compute_streak_and_grid (GREEN) | d34b67f | Done |

## What Was Built

### `memory/firestore_db.py` additions

**`_is_scheduled(target_date, schedule_history)`** — pure helper that finds the latest `effective_from <= target_date` revision and checks if the date falls on a scheduled day. Used inside `compute_streak_and_grid` and `get_pending_today`. Mon=0/Sun=6 weekday convention matches `_advance_once`.

**`compute_streak_and_grid(habit_id, schedule_history, completions, today, window_days=365)`** — pure function; all arithmetic on `datetime.date` objects so Israel DST transitions are invisible. Four states:
- `done` — scheduled + completion present
- `missed` — scheduled, before yesterday, no completion (confirmed, D-12)
- `pending` — today or yesterday, no completion (still in backfill window, D-11/D-12)
- `not-scheduled` — habit not scheduled for this date

Streak walk: `done` +1, `missed` breaks, `not-scheduled`/`pending` neutral (D-10, Pitfall 6).

**`HabitStore`** — follows TaskStore class structure with MealStore subcollection path:
- `_COLLECTION = "habits"`, `_COMPLETIONS = "habit_completions"`
- `create()`: seeds `schedule_history` from `days` field; strips `updated_at` from return
- `update()`: appends schedule_history revision when `days` changes (D-19/Pitfall 7); simple patch otherwise
- `log_completion()`: idempotent toggle; `done=False` deletes record; `dose_taken` recorded (D-09); `logged_at` as plain ISO string (H-28-IV)
- `get_completions_for_date()`: `_jsonsafe_doc` on all reads (Pitfall 1)
- `get_pending_today()`, `get_history()`, `get_summary()`: read methods; never raise; use `collection_group("records")` for cross-date completion queries

### `tests/test_habit_store.py` (32 tests)

Five test classes, all GREEN:
- **TestHabitStoreCRUD** (11 tests): create/list_active/update/soft_delete/restore; D-19 revision-append assertion
- **TestHabitCompletion** (6 tests): log_completion toggle; `_jsonsafe_doc` guard; `logged_at` plain-string invariant
- **TestStreakComputation** (6 tests): pure reset on miss; non-scheduled neutral; pending neutral (Pitfall 6); backfill repairs streak (D-11)
- **TestDST** (2 tests): spring-forward 2026-03-27 + fall-back 2026-10-25 (HABIT-03 mandate)
- **TestGridDerivation** (7 tests): four-state mapping; rolling-year length; D-19 effective-dated schedule revision

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _FakeRecordsCol yielded wrong snap.id**
- **Found during:** Task 2 GREEN — `test_get_completions_for_date_returns_dict` failed
- **Issue:** `_FakeDoc.__init__` sets `self.id = data.get("id", "")` but completion records have `habit_id` not `id`; `get_completions_for_date` uses `snap.id` as dict key → result keyed by `""` not the habit_id
- **Fix:** `_FakeRecordsCol.stream()` explicitly sets `doc.id = hid` (the dict key) after creating `_FakeDoc`
- **Files modified:** `tests/test_habit_store.py`

**2. [Rule 1 - Bug] Jsonsafe test used non-isoformat sentinel**
- **Found during:** Task 2 GREEN — `test_get_completions_for_date_applies_jsonsafe` failed
- **Issue:** Test used `object()` as sentinel but `_jsonsafe_value` only converts values with `.isoformat()` (the real `DatetimeWithNanoseconds` has it); bare `object()` passes through and json.dumps raises
- **Fix:** Replaced `object()` sentinel with `MagicMock()` that has `.isoformat.return_value = "2026-..."` — properly simulates what Firestore returns

**3. [Rule 1 - Bug] D-19 test used wrong weekday for today**
- **Found during:** Task 2 GREEN — `test_effective_dated_schedule_revision` failed with `not-scheduled != pending`
- **Issue:** Test comment said "today = 2026-06-30 (Monday)" but June 30 2026 is Tuesday (weekday=1), not in `days=[0]` → "not-scheduled" was correct for that date
- **Fix:** Changed `today=date(2026, 6, 30)` to `today=date(2026, 6, 29)` (confirmed Monday via Python)

## Known Stubs

None. This plan implements a data layer with no UI; no stub values flow to rendering.

## Threat Flags

None. The store is purely additive; no new network endpoints, auth paths, or trust-boundary crossings in this plan. API routes and auth are Plan 02's scope.

## Self-Check: PASSED

- `tests/test_habit_store.py` exists and has 32 passing tests
- `git log --oneline | grep "28-01"` → commits a5ff26d and d34b67f
- `grep -n "class HabitStore\|def compute_streak_and_grid\|def _is_scheduled" memory/firestore_db.py` → all three defined at lines 3040, 2959, 2929
- Regression: test_task_store 61/61, test_meal_store 10/10 still green
