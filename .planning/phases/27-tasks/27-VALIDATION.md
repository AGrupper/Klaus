---
phase: 27
slug: tasks
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `27-RESEARCH.md` § Validation Architecture + § Security Domain.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest (Python) — **run per-file** (grpc/protobuf segfaults on full-suite collection) |
| **Framework (frontend)** | Vitest 3.2.4 (`npm test` in `frontend/`) |
| **Config file** | backend: `tests/` (Firestore mocked via `_install_firestore_mock()` pattern in `tests/test_firestore_db.py`); frontend: `frontend/vitest.config.*` |
| **Quick run command** | `pytest tests/test_task_store.py -x` + `cd frontend && npm test -- --run src/utils/parseTaskInput.test.ts` |
| **Full suite command** | `pytest tests/test_task_store.py tests/test_web_server.py tests/test_tools.py tests/test_autonomous.py -x` + `cd frontend && npm test` |
| **Estimated runtime** | ~30 seconds (per-file pytest + targeted vitest) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_task_store.py -x` (+ `npm test -- --run src/utils/parseTaskInput.test.ts` for frontend tasks)
- **After every plan wave:** Run the full suite command above, plus the regression check `pytest tests/test_tools.py tests/test_autonomous.py tests/test_ticktick_tool.py -x` to catch tool-swap regressions
- **Before `/gsd:verify-work`:** Full task suite green AND the existing 1153+ baseline holds
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Requirement-level map from research (task IDs assigned by the planner; executor binds each row to the concrete `{27}-{plan}-{task}` ID it implements). Threat refs link to the PLAN `<threat_model>` blocks (§ Security Domain below).

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| TASK-01 | `TaskStore` create/update/delete | T-27-AC / T-27-IV | mutation requires `require_hub_session`; title/notes length-validated | unit (Py) | `pytest tests/test_task_store.py::TestTaskStoreCRUD -x` | ❌ W0 | ⬜ pending |
| TASK-01 | `TaskListStore` create/list/delete (+ Inbox default) | T-27-AC | session = owner check | unit (Py) | `pytest tests/test_task_store.py::TestTaskListStore -x` | ❌ W0 | ⬜ pending |
| TASK-01 | `/api/tasks` CRUD returns 200 + JSON-safe shape | T-27-IV | Pydantic `CreateTaskInput` validation | integration (Py) | `pytest tests/test_web_server.py::TestTaskRoutes -x` | ❌ W0 | ⬜ pending |
| TASK-02 | `_next_due_date`: daily/weekdays/weekly/monthly/every-N | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestNextDueDate -x` | ❌ W0 | ⬜ pending |
| TASK-02 | Month-end clamping (Jan 31 → Feb 28) | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestMonthEndClamping -x` | ❌ W0 | ⬜ pending |
| TASK-02 | Weekday wrapping (Fri/Sat → Mon) | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestWeekdayWrapping -x` | ❌ W0 | ⬜ pending |
| TASK-02 | Past-due roll-forward to next future occurrence (D-06) | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestPastDueRollForward -x` | ❌ W0 | ⬜ pending |
| TASK-02 | Recurring complete generates next + clears current (D-15) | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestRecurringComplete -x` | ❌ W0 | ⬜ pending |
| TASK-03 | `parseTaskInput("Buy milk tomorrow")` → `{due_date}` (Asia/Jerusalem) | T-27-TI | token regex strips before chrono; plain-text title | unit (TS) | `npm test -- --run src/utils/parseTaskInput.test.ts` | ❌ W0 | ⬜ pending |
| TASK-03 | `parseTaskInput("meeting #work !high friday")` → correct tokens | T-27-TI | token injection neutralized | unit (TS) | same file | ❌ W0 | ⬜ pending |
| TASK-03 | Near-midnight timezone: "tomorrow" resolves in Asia/Jerusalem | — | N/A | unit (TS) | same file (refDate stub) | ❌ W0 | ⬜ pending |
| TASK-04 | `TaskStore.complete()` sets `status="completing"` | T-27-REP | hard-delete rejected unless doc is `completing` | unit (Py) | `pytest tests/test_task_store.py::TestSoftComplete -x` | ❌ W0 | ⬜ pending |
| TASK-04 | Undo reverts status; recurring undo deletes generated next | — | N/A | unit (Py) | `pytest tests/test_task_store.py::TestUndoComplete -x` | ❌ W0 | ⬜ pending |
| TASK-04 | Completion micro-animation present in `TaskRow` | — | N/A | manual (visual) | n/a | — | ⬜ manual |
| TASK-05 | Native task tool schemas present in `TOOL_SCHEMAS`; `add_task` removed | — | N/A | unit (Py) | `pytest tests/test_tools.py::TestNativeTaskTools -x` | ❌ W0 | ⬜ pending |
| TASK-05 | `_gather_native_overdue()` returns `[{title, due}, ...]` from `TaskStore` | T-27-ID | no TickTick/native overlap (D-09 order) | unit (Py) | `pytest tests/test_autonomous.py::TestNativeOverdueGather -x` | ❌ W0 | ⬜ pending |
| TASK-05 | `"ticktick_overdue"` situation key still present in jobs dict | — | N/A | unit (Py) | `pytest tests/test_autonomous.py::TestJobsDict -x` | ❌ W0 | ⬜ pending |
| TASK-06 | Migration order: native verified (UAT) before TickTick tools removed | — | N/A | manual | n/a | — | ⬜ manual |
| TASK-07 | `/api/tasks/summary` returns `{due_today, overdue}` | T-27-AC | session-scoped | unit (Py) | `pytest tests/test_task_store.py::TestGetSummary -x` | ❌ W0 | ⬜ pending |
| TASK-07 | `useTaskSummary` hook fetches `/api/tasks/summary` | — | N/A | unit (TS) | `npm test -- --run src/hooks/useTaskSummary.test.ts` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ❌ W0 = file created in Wave 0*

---

## Wave 0 Requirements

New test files needed (existing infrastructure covers the surrounding code; mock Firestore via `_install_firestore_mock()`):

- [ ] `tests/test_task_store.py` — covers TASK-01/02/04/07 (CRUD, recurrence math, soft-complete/undo, summary)
- [ ] `tests/test_web_server.py` extensions — `TestTaskRoutes`: `/api/tasks*` CRUD + summary (TASK-01/07)
- [ ] `tests/test_tools.py` extensions — `TestNativeTaskTools`: native schemas registered; `add_task` schema + `_handle_add_task` removed (TASK-05)
- [ ] `tests/test_autonomous.py` extensions — `TestNativeOverdueGather` (return shape) + `TestJobsDict` (`"ticktick_overdue"` key retained) (TASK-05)
- [ ] `frontend/src/utils/parseTaskInput.test.ts` — pure-function parser, ≥8 cases incl. refDate-stubbed timezone (TASK-03)
- [ ] `frontend/src/hooks/useTaskSummary.test.ts` — mirrors `useChat.test.tsx` pattern (TASK-07)
- [ ] **Firestore composite indexes** created in Wave 0: `(status, due_date)` for overdue gather + `(list_id, status, due_date)` for list-scoped queries

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Completion micro-animation | TASK-04 | Animation timing/visual — not assertable in unit tests | Complete a task in the hub; observe the micro-animation then undo toast within the window |
| Quick-add FAB (phone) / keyboard shortcut (desktop) end-to-end | TASK-03 | Cross-device input affordance + live-resolve UX | On phone: tap FAB, type "gym tomorrow #health !high", confirm parsed chips; on desktop: trigger shortcut, same |
| Migration ordering | TASK-06 | Operational sequence across deploys + manual re-entry | Native tasks live + UAT-passed → THEN remove TickTick tools (Wave 4) → THEN cancel subscription |
| Undo survives the window mid-reload edge case | TASK-04 | Real browser reload timing (A3 assumption) | Complete a task, reload within the undo window; confirm acceptable behavior (task gone) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (6 test files + composite indexes)
- [ ] No watch-mode flags (vitest always `--run`; pytest always per-file `-x`)
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
