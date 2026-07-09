---
phase: 27-tasks
plan: 01
subsystem: backend-datastore
tags: [firestore, taskstore, recurrence, tdd, wave-0]
dependency_graph:
  requires: []
  provides: [TaskStore, TaskListStore, _next_due_date, Wave0TestScaffolds]
  affects: [27-02-routes, 27-03-tools, 27-04-frontend, 27-05-timeline]
tech_stack:
  added: []
  patterns: [StrengthSessionStore-pattern, FollowupStore-read-discipline, TDD-RED-GREEN]
key_files:
  created:
    - tests/test_task_store.py
    - frontend/src/utils/parseTaskInput.test.ts
    - frontend/src/hooks/useTaskSummary.test.ts
  modified:
    - memory/firestore_db.py
    - tests/test_web_server.py
    - tests/test_tools.py
    - tests/test_autonomous.py
    - docs/DEPLOYMENT.md
decisions:
  - "_advance_once factored out so _next_due_date D-06 roll-forward is a true while loop (not single-step break)"
  - "due_date stored as plain YYYY-MM-DD string — never SERVER_TIMESTAMP (T-27-IV threat eliminated)"
  - "Inbox is implicit (list_id='inbox') — no Firestore document for Inbox in TaskListStore"
  - "complete() sets status=completing + creates next-instance; undo_complete() reverts + deletes next-instance"
  - "Composite index creation gated as user_setup operator step (auto-mode blocked production gcloud writes)"
requirements-completed: [TASK-01, TASK-02]
metrics:
  duration: "~30 minutes"
  completed: "2026-06-18"
  tasks_completed: 3
  files_modified: 8
---

# Phase 27 Plan 01: TaskStore + Wave 0 Test Scaffolds Summary

## One-liner

Firestore-native `TaskStore` + `TaskListStore` + `_next_due_date` recurrence engine with five cadences, D-06 roll-forward loop, and six Wave 0 test files providing automated targets for all downstream plans.

## What Was Built

### Task 1 + 2: Recurrence engine + TaskStore/TaskListStore (TDD)

**`_advance_once(base, rule)` + `_next_due_date(current_due, completed_on, rule)`** added to `memory/firestore_db.py` after `BenchmarkStore`:

- Five cadences: `daily` (+1 day) / `weekdays` (skip Sat/Sun) / `weekly` (+7 days) / `monthly` (same day, `calendar.monthrange` clamp) / `every_n_days` (+N days)
- Two anchors: `schedule` (base = `current_due`) and `completion` (base = `completed_on`)
- D-06 roll-forward: a real `while candidate <= completed_on` loop — not a single-step `break`. A weekly task with `current_due=2026-05-01` completed on `2026-06-18` resolves in ONE call to `2026-06-19` (7 weekly advances; a single-step implementation returns `2026-05-08` and fails the test)

**`TaskStore` (`_COLLECTION = "tasks"`):**
- `create()`: uuid4 hex id, defaults `status=active`/`list_id=inbox`/`priority=none`, `due_date`/`due_time` as plain strings, only `updated_at` as `SERVER_TIMESTAMP`
- `get()`, `list(list_id=None)`, `update()`, `delete()`: standard CRUD following StrengthSessionStore discipline
- `complete(task_id, completed_on_iso)`: sets `status=completing`, generates next recurring instance via `_next_due_date`, returns `{"next_id": str|None}`
- `undo_complete(task_id, next_id=None)`: reverts `status=active`, deletes next instance if `next_id` provided
- `get_overdue(today_iso)`: active tasks with `due_date < today_iso` (server-side FieldFilter)
- `get_summary(today_iso)`: returns `{"due_today": int, "overdue": int}` — counts from active tasks

**`TaskListStore` (`_COLLECTION = "task_lists"`):**
- `create(name)`, `list()`, `rename(list_id, name)`, `delete(list_id)`
- Inbox is implicit (no Firestore doc), never returned by `list()`

### Task 3: Wave 0 test scaffolds + DEPLOYMENT.md

**Six Wave 0 files created or extended:**
1. `tests/test_task_store.py` — 59 tests, fully green (4 recurrence classes + 6 CRUD/behavior classes)
2. `tests/test_web_server.py` — `TestTaskRoutes` added (11 skip-marked, implemented in 27-02)
3. `tests/test_tools.py` — `TestNativeTaskTools` added (9 skip-marked, implemented in 27-03)
4. `tests/test_autonomous.py` — `TestNativeOverdueGather` + `TestJobsDict` added (6 skip-marked, implemented in 27-03)
5. `frontend/src/utils/parseTaskInput.test.ts` — 10 skip-marked NL-parse cases incl. timezone edge case (TASK-03)
6. `frontend/src/hooks/useTaskSummary.test.ts` — 5 skip-marked renderHook stub (TASK-07)

**DEPLOYMENT.md §21 Firestore Composite Indexes:** Two new rows documenting the `tasks` composite indexes with the exact `gcloud firestore indexes composite create` commands.

## Verification

```
pytest tests/test_task_store.py -x              → 59 passed
pytest tests/test_firestore_db.py -x            → 31 passed (baseline unaffected)
pytest tests/test_autonomous.py -x              → 46 passed, 6 skipped
grep -n "monthrange" memory/firestore_db.py     → line 2445 (confirmed)
grep -n '_COLLECTION = "tasks"' memory/...      → line 2534 (confirmed)
grep -n '_COLLECTION = "task_lists"' memory/... → line 2808 (confirmed)
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `65dcfca` | test | TDD RED: recurrence tests + failing TaskStore CRUD tests |
| `2ecf8a0` | feat | TDD GREEN: TaskStore + TaskListStore implementation |
| `da4907f` | feat | Wave 0 scaffolds (5 test files) + DEPLOYMENT.md indexes |

## Deviations from Plan

### Operator Step Required — Composite Index Creation

**Found during:** Task 3

**Issue:** The plan called for running `gcloud firestore indexes composite create` commands against `--project=klaus-agent --database=klaus-firestore`. Auto-mode blocked this as a production infrastructure modification requiring explicit user authorization.

**Fix:** Documented the two `gcloud` commands in `docs/DEPLOYMENT.md §21` with the exact create commands. The operator must run these manually before Phase 27 goes live.

**Commands to run:**
```bash
gcloud firestore indexes composite create \
  --project=klaus-agent --database=klaus-firestore \
  --collection-group=tasks --query-scope=COLLECTION \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=due_date,order=ascending

gcloud firestore indexes composite create \
  --project=klaus-agent --database=klaus-firestore \
  --collection-group=tasks --query-scope=COLLECTION \
  --field-config=field-path=list_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=due_date,order=ascending
```

### test_tools.py Collection Error (Pre-existing)

**Found during:** Task 3 verification

**Issue:** `tests/test_tools.py` fails to collect with `ModuleNotFoundError: No module named 'googleapiclient'` — a pre-existing environment issue. The `TestNativeTaskTools` class was added successfully (grep confirms it's at line 858) but pytest can't collect it in this environment. The class will be collected correctly in the CI environment where all dependencies are installed.

**Impact:** None — the class text is in the file; CI will collect it.

## Known Stubs

None. All implementations are complete for this plan. The skip-marked scaffold tests are intentionally deferred to their respective downstream plans (27-02, 27-03, 27-04).

## Threat Flags

None. T-27-IV (due_date as SERVER_TIMESTAMP) was mitigated — `due_date`/`due_time` are always stored as plain strings; only `updated_at` uses `SERVER_TIMESTAMP`. T-27-REP (raw delete) is properly layered — `TaskStore.delete()` is raw; the route layer (27-02) will enforce the `status=completing` gate.

## Self-Check: PASSED

Files created/modified:
- `memory/firestore_db.py` ✓ (contains `_next_due_date`, `TaskStore`, `TaskListStore`)
- `tests/test_task_store.py` ✓ (59 tests pass)
- `frontend/src/utils/parseTaskInput.test.ts` ✓ (10 skip-marked cases)
- `frontend/src/hooks/useTaskSummary.test.ts` ✓ (5 skip-marked cases)
- `docs/DEPLOYMENT.md` ✓ (two tasks composite index rows added)

Commits verified in git log: `65dcfca`, `2ecf8a0`, `da4907f`
