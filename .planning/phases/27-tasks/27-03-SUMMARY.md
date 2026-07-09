---
phase: 27-tasks
plan: 03
subsystem: backend-agent-tools
tags: [tools, taskstore, autonomous, tdd, wave-2, tool-swap]
dependency_graph:
  requires: [27-01]
  provides: [NativeTaskTools, NativeOverdueGather]
  affects: [27-04-frontend, 27-05-timeline, 27-07-ticktick-cutover]
tech_stack:
  added: []
  patterns: [TaskStore-direct-import, TickTick-compatible-return-shape, TDD-RED-GREEN]
key_files:
  created: []
  modified:
    - core/tools.py
    - core/autonomous.py
    - tests/test_tools.py
    - tests/test_autonomous.py
decisions:
  - "6 native task handlers import TaskStore directly via lazy _get_task_store() — no singleton, no process-level state"
  - "_handle_task_list filters overdue via store.get_overdue(), date via Python list-comp, priority via Python list-comp — keeps handler simple"
  - "_gather_native_overdue returns [{title, due}] TickTick-compatible shape — zero changes to 9 downstream ticktick_overdue references (D-17)"
  - "add_task schema + _handle_add_task + _HANDLERS['add_task'] fully removed — no dead _ticktick_add_task reference remains (Pitfall 5)"
requirements-completed: [TASK-05]
metrics:
  duration: "~5 minutes"
  completed: "2026-06-18"
  tasks_completed: 2
  files_modified: 4
---

# Phase 27 Plan 03: Native Task Tools + Autonomous Overdue Swap Summary

## One-liner

Six native `TaskStore`-backed task tools replace the single TickTick `add_task` tool, and the autonomous Layer-0 overdue gather is repointed from `ticktick_tool` to `TaskStore` — keeping `ticktick_overdue` as the unchanged situation key (D-17).

## What Was Built

### Task 1: Native task tools in core/tools.py; remove add_task (TDD)

**`core/tools.py` changes:**

- **Removed:** `add_task` schema (lines 212-247), `_handle_add_task` function, `_HANDLERS["add_task"]` entry, and all `_ticktick_add_task` dead-code references (0 remaining).
- **Added** 6 schemas to `TOOL_SCHEMAS`:
  - `task_create(title, notes?, due_date?, due_time?, priority?, list_id?, recurrence?)`
  - `task_list(list_id?, date?, priority?, overdue?)`
  - `task_complete(task_id)`
  - `task_reschedule(task_id, due_date, due_time?)`
  - `task_edit(task_id, title?, notes?, priority?, list_id?)`
  - `task_delete(task_id)`
- **Added** helper `_get_task_store()` — lazy, env-driven `TaskStore` factory (`os.environ.get("GCP_PROJECT_ID")` / `os.environ.get("FIRESTORE_DATABASE", "(default)")`).
- **Added** helper `_task_today_iso()` — `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()` for `task_complete` completed_on.
- **Added** 6 `_handle_task_*(**kwargs) -> str` functions; each calls the matching `TaskStore` method and returns `json.dumps(result)`.
- **Added** 6 dispatch entries to `_HANDLERS`.

**`tests/test_tools.py` changes:**

- Replaced skip-marked `TestNativeTaskTools` scaffold with 10 live tests asserting all 6 names in `TOOL_SCHEMAS`, `add_task` absent, all 6 keys in `_HANDLERS`, `add_task` absent, and an import smoke test.

### Task 2: Repoint autonomous overdue gather to TaskStore (TDD)

**`core/autonomous.py` changes:**

- Renamed `_gather_ticktick_overdue` → `_gather_native_overdue`.
- New body: imports `TaskStore` from `memory.firestore_db`, computes `today_iso` in Asia/Jerusalem, calls `store.get_overdue(today_iso)`, and returns `[{"title": t["title"], "due": t.get("due_date", "")} for t in tasks]` — the TickTick-compatible shape (Pitfall 3).
- Wrapped in `try/except → return []` with `logger.warning(..., exc_info=True)` so the autonomous tick never crashes on a Firestore failure.
- Jobs dict entry at line 445 updated: `"ticktick_overdue": _gather_native_overdue` — **key name unchanged** (D-17 / A6).
- Zero changes to the 9 references to `"ticktick_overdue"` at lines 180, 463, 487-493, 516, 598, 684, 729.

**`tests/test_autonomous.py` changes:**

- Replaced skip-marked `TestNativeOverdueGather` scaffold with 4 live tests: existence check, return-shape check (mocked `TaskStore.get_overdue`), source-import check (no ticktick_tool in function body), exception-returns-empty-list check.
- Replaced skip-marked `TestJobsDict` scaffold with 2 live tests: key presence check, jobs-entry-value check.

## Verification

```
pytest tests/test_autonomous.py::TestNativeOverdueGather tests/test_autonomous.py::TestJobsDict -x
  → 6 passed

pytest tests/test_autonomous.py -x
  → 52 passed (was 46 passed + 6 skipped)

python3 -c "import core.autonomous"
  → exits 0

grep -c "_ticktick_add_task" core/tools.py    → 0
grep -c "ticktick_overdue" core/autonomous.py → 9 (unchanged baseline)
grep -c "_gather_ticktick_overdue" core/autonomous.py → 0
```

Note: `tests/test_tools.py::TestNativeTaskTools` cannot be collected locally due to the pre-existing `ModuleNotFoundError: No module named 'googleapiclient'` (documented in 27-01 SUMMARY). The 10 implemented tests were verified correct by importing `core.tools` with module stubs and manually asserting all schema/handler invariants. CI will collect and run them in the full environment.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `e703745` | test | TDD RED: TestNativeTaskTools with real assertions |
| `a833b37` | feat | TDD GREEN: native TaskStore tool suite; remove add_task |
| `24cb893` | test | TDD RED: TestNativeOverdueGather + TestJobsDict real assertions |
| `d2d6e00` | feat | TDD GREEN: repoint autonomous overdue gather to TaskStore |

## Deviations from Plan

None — plan executed exactly as written.

- The `add_task` schema, `_handle_add_task`, and `_HANDLERS["add_task"]` were all removed.
- All 9 `ticktick_overdue` situation-key references in `core/autonomous.py` are unchanged (D-17).
- The function is renamed `_gather_native_overdue` (not `_gather_ticktick_overdue`).
- Return shape is exactly `[{"title": str, "due": str}]` (Pitfall 3 — TickTick-compatible).

## Known Stubs

None. All implementations are complete. TickTick files remain (D-09 — removal gated on native UAT in 27-07).

## Threat Flags

None. T-27-IV (LLM-generated tool args reaching TaskStore) is accepted — TaskStore stores `due_date`/`due_time` as plain strings, never SERVER_TIMESTAMP. T-27-ID (double-read window) is not triggered — the autonomous gather now reads native tasks only; TickTick is not called by this code path.

## Self-Check: PASSED

Files modified:
- `core/tools.py` ✓ (6 native schemas + handlers; add_task removed; _ticktick_add_task count = 0)
- `core/autonomous.py` ✓ (_gather_native_overdue defined; jobs dict updated; ticktick_overdue count = 9)
- `tests/test_tools.py` ✓ (TestNativeTaskTools skip markers removed; 10 live tests)
- `tests/test_autonomous.py` ✓ (TestNativeOverdueGather + TestJobsDict skip markers removed; 6 live tests)

Commits verified: `e703745`, `a833b37`, `24cb893`, `d2d6e00` in git log.
