---
phase: 27-tasks
plan: 02
subsystem: backend-api
tags: [fastapi, tasks, pydantic, tdd, wave-2, session-auth, hub]
dependency_graph:
  requires: [27-01]
  provides: [TaskRoutesAPI, TaskListRoutesAPI, CreateTaskInput, UpdateTaskInput, CreateListInput, TestTaskRoutes]
  affects: [27-04-frontend, 27-05-timeline]
tech_stack:
  added: []
  patterns: [Pydantic-BaseModel-validation, run_in_executor-sync-Firestore, _jsonsafe_doc-output, Depends-require_hub_session]
key_files:
  created: []
  modified:
    - interfaces/web_server.py
    - tests/test_web_server.py
decisions:
  - "/api/tasks/summary registered BEFORE /api/tasks/{task_id} so the literal path is matched first (FastAPI first-match ordering)"
  - "store.list called with keyword arg via lambda wrapper so the mock assertion is unambiguous"
  - "hard-delete gate: GET task first, reject 409 if status != 'completing'; task not found also rejects (None check)"
  - "tasks in a deleted list retain their list_id — reassign-to-inbox sweep deferred to a future plan"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-18"
  tasks_completed: 2
  files_modified: 2
---

# Phase 27 Plan 02: Task + Task-List CRUD Routes Summary

## One-liner

FastAPI CRUD layer for `/api/tasks/*` and `/api/task-lists/*` with Pydantic input validation (ASVS V5), session-cookie auth gating, soft-complete → undo → 409-gated hard-delete mechanic, and 16-test green TestTaskRoutes suite.

## What Was Built

### Task 1: Task + task-list CRUD routes with Pydantic validation (TDD)

**Pydantic models added to `interfaces/web_server.py`** (after the `/api/chat/messages` route, before SPA mount):

- `CreateTaskInput`: `title` 1..500, `notes` ≤10 000, `due_date` `^\d{4}-\d{2}-\d{2}$`, `due_time` `^([01]\d|2[0-3]):[0-5]\d$`, `priority` Literal enum, `list_id` free string — all field constraints from RESEARCH § Security Domain (T-27-IV)
- `UpdateTaskInput`: all fields optional (PATCH semantics, `exclude_unset=True` in route)
- `CreateListInput`: `name` 1..200

**Routes added** (all behind `Depends(require_hub_session)`, all output via `_jsonsafe_doc`, all sync Firestore calls via `loop.run_in_executor`):

| Route | Method | Store call | Notes |
|-------|--------|------------|-------|
| `/api/tasks` | POST | `TaskStore.create(dict)` | `list_id=None` → coerced to `"inbox"` |
| `/api/tasks` | GET | `TaskStore.list(list_id=...)` | Optional `list_id` query param |
| `/api/tasks/summary` | GET | `TaskStore.get_summary(today_iso)` | Declared BEFORE `/{task_id}` to avoid shadowing |
| `/api/tasks/{task_id}` | PATCH | `TaskStore.update(id, patch)` | `exclude_unset=True` |
| `/api/tasks/{task_id}/complete` | POST | `TaskStore.complete(id, completed_on_iso)` | Asia/Jerusalem today |
| `/api/tasks/{task_id}/undo` | POST | `TaskStore.undo_complete(id)` | Returns `{"ok": True}` |
| `/api/tasks/{task_id}/hard-delete` | POST | `TaskStore.get` then `TaskStore.delete` | 409 if `status != "completing"` (T-27-REP) |
| `/api/task-lists` | POST | `TaskListStore.create(name)` | |
| `/api/task-lists` | GET | `TaskListStore.list()` | Inbox `{"id":"inbox","name":"Inbox"}` prepended |
| `/api/task-lists/{list_id}` | PATCH | `TaskListStore.rename(id, name)` | |
| `/api/task-lists/{list_id}` | DELETE | `TaskListStore.delete(id)` | Returns `{"ok": True}` |

### Task 2: TestTaskRoutes integration tests

Replaced the 11 skip-marked Wave 0 scaffold stubs with 16 real integration tests using the existing `_stub_web_server_imports()` pattern and `ws.app.dependency_overrides[require_hub_session]`.

Helper factories added above the class:
- `_make_task_store_mock(...)` — MagicMock with configurable return values
- `_make_list_store_mock(...)` — MagicMock with configurable return values

Tests cover:
- `test_post_tasks_returns_200_with_id` — create task → id present in response
- `test_post_tasks_empty_title_rejected` — empty title → 400/422 (Pydantic min_length=1)
- `test_post_tasks_malformed_due_date_rejected` — `"2026/06/20"` → 400/422 (regex)
- `test_get_tasks_returns_active_tasks` — list → `{tasks: [...]}`
- `test_get_tasks_by_list_id_filters` — `?list_id=inbox` → `store.list(list_id="inbox")` called
- `test_get_tasks_summary_returns_due_today_and_overdue` — `{due_today, overdue}` shape
- `test_patch_tasks_updates_title` — updated title in response
- `test_post_tasks_complete_returns_next_id` — `{next_id}` present
- `test_post_tasks_undo_reverts_to_active` — 200 ok
- `test_post_tasks_hard_delete_on_active_task_returns_409` — T-27-REP guard
- `test_post_tasks_hard_delete_on_completing_task_returns_200` — and `delete` called
- `test_tasks_routes_require_hub_session_401` — T-27-AC: unauthenticated → 401
- `test_post_task_lists_creates_a_list` — list created, name in response
- `test_get_task_lists_prepends_inbox` — Inbox is first, len == 2
- `test_patch_task_lists_renames_a_list` — renamed name in response
- `test_delete_task_lists_returns_200` — 200 and `store.delete` called

## Verification

```
pytest tests/test_web_server.py::TestTaskRoutes -x   → 16 passed
pytest tests/test_web_server.py -x                   → 51 passed (all existing tests unbroken)
grep -n "/api/tasks/summary" interfaces/web_server.py → line 1811
grep -n "class CreateTaskInput" interfaces/web_server.py → line 1738
Depends(require_hub_session) present on all 11 new route handlers ✓
hard-delete raises HTTPException 409 when status != 'completing' ✓
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `cff1876` | test | TDD RED — TestTaskRoutes integration tests (16 tests, all failing 404) |
| `19c86f6` | feat | TDD GREEN — /api/tasks/* + /api/task-lists/* CRUD routes + Pydantic models |

## Deviations from Plan

### store.list called via lambda for keyword-argument hygiene

**Found during:** Task 1 / GREEN verification

**Issue:** `run_in_executor(None, store.list, list_id)` passes `list_id` positionally.
The test expected `store.list(list_id="inbox")` (keyword call).

**Fix:** Wrapped with `lambda: store.list(list_id=list_id)` so the call is explicit and the mock assertion is unambiguous.

**Files modified:** `interfaces/web_server.py` (single line change)

**Commit:** `19c86f6`

## Known Stubs

None. All 11 routes are fully implemented. Task-list deletion leaves tasks with their old `list_id` (documented in route docstring as a deferred concern for a future plan).

## Threat Flags

None beyond the plan's own threat register. All three threats mitigated:

| Threat | Mitigation confirmed |
|--------|---------------------|
| T-27-AC | `Depends(require_hub_session)` on all 11 handlers; 401 test passes |
| T-27-IV | Pydantic rejects empty title → 422, malformed due_date → 422 |
| T-27-REP | hard-delete handler fetches task, raises 409 if `status != "completing"` |

## Self-Check: PASSED

Files modified:
- `interfaces/web_server.py` ✓ (contains `CreateTaskInput`, `UpdateTaskInput`, `CreateListInput`, `/api/tasks/summary`, 11 route handlers)
- `tests/test_web_server.py` ✓ (contains `TestTaskRoutes` with 16 real tests, no skip markers)

Commits verified in git log: `cff1876`, `19c86f6`
