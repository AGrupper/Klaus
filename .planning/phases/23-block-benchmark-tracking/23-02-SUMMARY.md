---
phase: 23-block-benchmark-tracking
plan: "02"
subsystem: core/tools
tags: [tools, brain-direct, block, benchmark, tdd, access-control]
dependency_graph:
  requires: [BlockStore, BenchmarkStore, get_week_num]
  provides: [get_plan, get_block_status, log_benchmark, get_benchmark_history, start_block, end_block, epley_1rm]
  affects: [core/tools.py]
tech_stack:
  added: []
  patterns: [brain-direct-tool, worker-exclusion, read-handler-json-dumps, write-handler-try-except, _jsonsafe_doc]
key_files:
  created:
    - tests/test_tool_registration_phase23.py
  modified:
    - core/tools.py
decisions:
  - "All 6 new tools are brain-direct (SMART_AGENT_DIRECT_TOOLS) and excluded from WORKER_TOOL_SCHEMAS (T-23-05 structural access control)"
  - "update_plan NOT re-added — already registered since Phase 21 (Pitfall 2); test_update_plan_not_duplicated guards it"
  - "get_plan/get_block_status surface the active block via date-range get_current() — no start_block precondition (D-01)"
  - "get_block_status.facet_deltas is RAW (current - prior-block value) — no trend projection (Phase 25 scope)"
  - "log_benchmark handler defers facet validation to BenchmarkStore.log_benchmark ValueError, caught and returned as {error:...} (T-23-06)"
  - "epley_1rm helper exposed for top-set 1RM derivation; brain normally passes the computed value"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
requirements: [BLOCK-01, BLOCK-03]
---

# Phase 23 Plan 02: 6 Brain-Direct Block/Benchmark Tools Summary

## One-liner

Six new brain-direct tools (`get_plan`, `get_block_status`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`) wired into `core/tools.py` — schemas, handlers, and `_HANDLERS` dispatch — giving the brain reactive chat-path access to block state and benchmark recording/comparison.

## What Was Built

### 6 TOOL_SCHEMAS entries (`core/tools.py`)
- **get_plan** (zero-arg) — profile/plan merged with date-resolved active block + week number
- **get_block_status** (zero-arg) — active block + its benchmarks + raw per-facet deltas vs prior block
- **log_benchmark** — required `date, facet, value, unit, block_id`; optional `notes`. Description names the 5-facet closed set and the Epley formula for top-sets.
- **get_benchmark_history** — required `facet`; optional `n`
- **start_block** / **end_block** — required `block_id` (bookkeeping; description notes date-resolution makes these optional)

### Registration (3 sites)
- 6 names added to `SMART_AGENT_DIRECT_TOOLS` (brain-direct)
- 6 names added to the `WORKER_TOOL_SCHEMAS` exclusion set (T-23-05 — worker cannot reach block/benchmark mutation)
- `update_plan` left untouched (single registration — Pitfall 2)

### Handlers (`core/tools.py`)
- `_block_stores()` — env-driven constructor for (BlockStore, BenchmarkStore, UserProfileStore)
- `_handle_get_plan()` — `UserProfileStore.load()` + `BlockStore.get_current()` (date range) + `get_week_num` against `plan_start_date` (default `2026-06-21`)
- `_handle_get_block_status()` — current block + `get_block_benchmarks` + `facet_deltas` (raw delta vs most recent value from a different block via `get_facet_history`)
- `_handle_log_benchmark(...)` — calls `BenchmarkStore.log_benchmark`; `ValueError` on bad facet caught → `{"error": ...}` (T-23-06)
- `_handle_get_benchmark_history(facet, n=10)`
- `_handle_start_block(block_id)` — `BlockStore.start_block` + `UserProfileStore.update({"current_block_id": block_id})`
- `_handle_end_block(block_id)` — `BlockStore.end_block` + `UserProfileStore.update({"current_block_id": None})`
- `epley_1rm(weight, reps)` helper — `round(weight * (1 + reps/30), 1)`

### Dispatch
- 6 `_HANDLERS` entries (zero-arg: `lambda args: _handle_x()`; arg: `lambda args: _handle_x(**args)`)

## Tests Written (9 total, all passing)

`tests/test_tool_registration_phase23.py` (mirrors phase-20 registration pattern, uses `isolated_modules` fixture + `_install_tools_mocks`):
- `test_six_new_tools_in_direct` — all 6 in `SMART_AGENT_DIRECT_TOOLS`
- `test_six_new_tools_excluded_from_worker` — none in `WORKER_TOOL_SCHEMAS` (T-23-05)
- `test_six_new_tools_in_handlers` — all 6 keys in `_HANDLERS`
- `test_six_new_tools_have_schemas` — schema shape per tool
- `test_update_plan_not_duplicated` — `update_plan` appears exactly once (Pitfall 2)
- `test_log_benchmark_schema_required_fields` / `test_get_benchmark_history_requires_facet`
- `test_zero_arg_tools_have_no_required` (get_plan, get_block_status)
- `test_handler_functions_defined` — all 6 `_handle_*` callable

## Deviations from Plan

None. Implemented as specified. (Plan suggested a `test_six_new_tools_have_schemas` plus additional shape assertions; I added explicit required-field tests for `log_benchmark`/`get_benchmark_history` and the zero-arg tools for stronger coverage.)

## Known Stubs

None.

## TDD Gate Compliance

- RED gate (test commit): 9-test registration file, 7 failing (2 trivially-true) — tools absent
- GREEN gate (feat commit): all 9 passing; `python -c "import core.tools"` exits 0 (no duplicate-key crash — Pitfall 2)

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: access-control | core/tools.py | 6 tools excluded from WORKER_TOOL_SCHEMAS (T-23-05 — structural) |
| threat_flag: input-validation | core/tools.py | log_benchmark handler catches store ValueError on bad facet (T-23-06) |

## Self-Check: PASSED

Files verified:
- FOUND: core/tools.py
- FOUND: tests/test_tool_registration_phase23.py
- FOUND: .planning/phases/23-block-benchmark-tracking/23-02-SUMMARY.md
