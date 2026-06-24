---
phase: 27-tasks
plan: 07
subsystem: ticktick-retirement
tags: [cutover, d-09, ticktick-removal, cron-repoint, wave-5]
dependency_graph:
  requires: [27-02, 27-03, 27-04, 27-05, 27-06]
  provides: [native-only-tasks]
  affects: []
tech_stack:
  removed: [mcp_tools/ticktick_tool.py, mcp_tools/ticktick_auth.py]
key_files:
  created: []
  modified:
    - memory/firestore_db.py
    - core/morning_briefing.py
    - core/nightly_review.py
    - core/reflection.py
    - core/heartbeat.py
    - core/self_manifest.py
    - core/tools.py
    - docs/DEPLOYMENT.md
    - CLAUDE.md
    - tests/test_autonomous.py
    - tests/test_morning_briefing.py
    - tests/test_nightly_review.py
  deleted:
    - mcp_tools/ticktick_tool.py
    - mcp_tools/ticktick_auth.py
    - tests/test_ticktick_tool.py
    - tests/test_ticktick_auth.py
decisions:
  - "Blocking-human UAT gate cleared by Amit after verifying native tasks live + manually re-entering open TickTick tasks (D-08/D-09)"
  - "ticktick_overdue situation key preserved unchanged (D-17) — 9 call-sites in core/autonomous.py"
  - "TaskStore.get_today_and_overdue() is the drop-in for the retired ticktick_tool.get_today_tasks()"
  - "Operator actions (cancel subscription, remove 4 secrets) deferred to AFTER deploy (Open Question 2)"
metrics:
  completed: "2026-06-24"
  tasks_completed: 2
  files_modified: 12
  files_deleted: 4
  net_lines: "-763"
---

# Phase 27 Plan 07: TickTick Cutover Summary

## One-liner

D-09 TickTick retirement, executed after the blocking-human UAT checkpoint was approved: deleted `ticktick_tool.py` + `ticktick_auth.py`, repointed the four remaining cron consumers to the native `TaskStore`, preserved the `ticktick_overdue` situation key (D-17), and documented the operator secret-cleanup runbook.

## What Was Built / Removed

### Blocking UAT checkpoint (cleared)

Amit verified native tasks end-to-end on the live hub (create/edit/complete/recurrence, quick-add, Klaus reschedule via chat, Today band + glance counts) and manually re-created his open TickTick tasks before approving removal. The cutover ran only after the explicit approval signal.

### Task 1: Delete TickTick + repoint consumers

**Scope deviation (recorded):** the plan stated the TickTick files were "unused after the 27-03 swap." That was inaccurate — `grep -rn ticktick` showed **four cron paths still read TickTick directly**. Deleting the files without repointing would have broken those crons at runtime. Repointed first:

- **New `TaskStore.get_today_and_overdue(today_iso)`** (`memory/firestore_db.py`) — a drop-in for the retired `ticktick_tool.get_today_tasks()`, returning the exact shape consumers read: `{"today": [{title,tags}], "overdue": [{title,due,tags}], "due_today": [], "staleness_warning": None}`. Native tasks have no tags → `tags` is always `[]`.
- **`core/morning_briefing.py`** — `data["tasks"]` now from `TaskStore.get_today_and_overdue(today_iso)`.
- **`core/nightly_review.py`** — same, evaluated as of tonight (`datetime.now(_TZ)`), not `tomorrow_iso`.
- **`core/reflection.py`** — `tasks_completed` count from the native store.
- **`core/heartbeat.py`** — removed the TickTick OAuth refresh probe (no token left to probe); the Google probe stays.
- **`core/self_manifest.py` / `core/tools.py`** — `add_task`→`task_create`, TickTick integration row → native Tasks, briefing description and module docstring updated.

Deleted `mcp_tools/ticktick_tool.py`, `mcp_tools/ticktick_auth.py` and their test files. **`ticktick_overdue` situation key preserved** (D-17): `grep -c ticktick_overdue core/autonomous.py` = 9, unchanged. All three entrypoints (`core.tools`, `core.autonomous`, `interfaces.web_server`) plus the four crons import cleanly.

Cron/autonomous test mocks repointed from `mcp_tools.ticktick_tool.get_today_tasks` to `memory.firestore_db.TaskStore`. (The autonomous-test patches were vestigial no-ops since the 27-03 swap; they only broke because the module was gone.)

### Task 2: Retirement runbook

- **`docs/DEPLOYMENT.md` §26** — documents the cutover + the operator cleanup: cancel the TickTick subscription **first**, then remove the four `TICKTICK_*` secrets from Cloud Run + Secret Manager (commands included). Migration was manual (D-08).
- **`CLAUDE.md` §4** — dropped the two deleted `mcp_tools/ticktick_*.py` lines.

## Verification

```
grep -rn "import ticktick|from mcp_tools import ticktick" core/ interfaces/   → none
python -c "import core.tools, core.autonomous, interfaces.web_server,
           core.morning_briefing, core.nightly_review, core.reflection,
           core.heartbeat"                                                    → OK
grep -c ticktick_overdue core/autonomous.py                                   → 9 (D-17 preserved)
pytest (per-file): task_store 61, tools 56, web_server 51, autonomous 52,
        heartbeat 22, reflection 8, morning_briefing 37, nightly_review 17    → all pass
grep -c "TickTick Retirement" docs/DEPLOYMENT.md                              → 1
grep -c "ticktick_tool.py" CLAUDE.md                                          → 0
```

(nightly_review exits with the documented grpc/protobuf GC segfault on interpreter shutdown — all 17 tests pass first; environmental, per STATE.md.)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `a51e3d5` | feat | Delete TickTick + repoint crons to native TaskStore (preserve ticktick_overdue key) |
| `c533d97` | docs | TickTick retirement runbook (DEPLOYMENT.md §26) + CLAUDE.md layout |

## Deviations from Plan

### Plan under-scoped the TickTick footprint

**Found during:** Task 1 recon (`grep -rn ticktick`).

**Issue:** The plan said `ticktick_tool.py` was "now unused by tools + autonomous after the 27-03 swap." In fact `morning_briefing`, `nightly_review`, `reflection`, and `heartbeat` all still imported it. Deleting the files as-written would have broken four production cron paths.

**Fix:** Added the native `TaskStore.get_today_and_overdue` helper and repointed all four consumers (drop-in shape, no prompt changes) before deleting; updated their test mocks.

**Rule:** Rule 3 (auto-fix — necessary scope expansion to fulfil the approved cutover without breaking runtime).

## Operator Actions (post-deploy)

1. Cancel the TickTick subscription.
2. After cancellation, remove `TICKTICK_ACCESS_TOKEN`, `TICKTICK_REFRESH_TOKEN`, `TICKTICK_CLIENT_ID`, `TICKTICK_CLIENT_SECRET` from Cloud Run + Secret Manager (see DEPLOYMENT.md §26).

## Self-Check: PASSED

- `mcp_tools/ticktick_tool.py` + `ticktick_auth.py` deleted ✓
- No live `import ticktick` in core/ or interfaces/ ✓
- Entrypoints + 4 crons import clean ✓
- `ticktick_overdue` key preserved (9 sites, D-17) ✓
- DEPLOYMENT.md retirement runbook + 4-secret cleanup ✓; CLAUDE.md layout updated ✓
- Backend tests green across all touched files ✓
