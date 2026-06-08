---
phase: 25-progress-projection-benchmark-trend-reporting
plan: "02"
subsystem: core/tools + core/pace_history + prompts/smart_agent
tags: [tool-registration, brain-direct, tdd, projection, PROG-02, benchmark, garmin-pace, D-04, CR-01]
dependency_graph:
  requires: [core/projection.py::project_goal_progress, memory/firestore_db.py::_BENCHMARK_FACETS]
  provides: [core/tools.py::get_goal_projection, core/pace_history.py::fetch_dense_pace_history]
  affects: [prompts/smart_agent.md, core/tools.py::_HANDLERS, core/tools.py::SMART_AGENT_DIRECT_TOOLS]
tech_stack:
  added: []
  patterns: [brain-direct-tool, facet-validation-V5-T23-01, ZoneInfo-CR-01, D-04-dense-vs-sparse, jsonsafe-doc-T25-06, fail-open-empty-list]
key_files:
  created:
    - core/pace_history.py
    - tests/test_tool_registration_phase25.py
  modified:
    - core/tools.py
    - prompts/smart_agent.md
decisions:
  - "D-04 honored — threshold_pace prefers dense Garmin Postgres history (fetch_dense_pace_history), falls back to BenchmarkStore only when no running data exists; strength facets always use BenchmarkStore"
  - "CR-01 lesson applied — today_iso via ZoneInfo('Asia/Jerusalem'), never date.today() in handler"
  - "pace derived from duration_sec/distance_m*1000 — RESOLVED Open Question #1; avg_pace column intentionally not read"
  - "get_goal_projection is brain-direct only (SMART_AGENT_DIRECT_TOOLS + WORKER exclusion set) — T-25-08"
  - "profiles.load() wrapped in _jsonsafe_doc before dated_goals extraction — T-25-06"
metrics:
  duration_seconds: 223
  completed_date: "2026-06-08"
  tasks_completed: 3
  files_created: 2
  tests_added: 5
---

# Phase 25 Plan 02: Reactive Projection Tool + Dense Pace Path Summary

**One-liner:** `get_goal_projection(facet)` brain-direct tool wired to the Plan-01 helper via D-04 dual-source-selection (dense Garmin Postgres for pace, sparse BenchmarkStore for strength), with ZoneInfo CR-01 today_iso, facet validation, and smart_agent prompt permission to cite computed numbers.

## What Was Built

`core/pace_history.py` — a new module exposing `fetch_dense_pace_history(today_iso)` which queries the Postgres `activities` table for running activities from the last 90 days and returns BenchmarkStore-shaped dicts `{date, facet:"threshold_pace", value, unit:"sec_per_km"}`. Pace is derived as `duration_sec / distance_m * 1000` (no `avg_pace` column read — RESOLVED Open Question #1). Fails open to `[]` on any error.

`core/tools.py` — `get_goal_projection` registered at all four sites:
1. `SMART_AGENT_DIRECT_TOOLS` — brain calls it directly
2. `TOOL_SCHEMAS` — schema with single required `facet` param + description of 5 valid facets
3. `WORKER_TOOL_SCHEMAS` exclusion set — worker cannot call it (T-25-08)
4. `_HANDLERS` — dispatches to `_handle_get_goal_projection`

`_handle_get_goal_projection(facet)` handler:
- Validates `facet` against `_BENCHMARK_FACETS` frozenset (T-25-05, mirrors T-23-01)
- Computes `today_iso` via `ZoneInfo("Asia/Jerusalem")` (CR-01 lesson, T-25-14)
- D-04 source selection: `threshold_pace` → `fetch_dense_pace_history` with BenchmarkStore fallback; strength facets → `BenchmarkStore.get_facet_history`
- Wraps `profiles.load()` in `_jsonsafe_doc` (T-25-06)
- Calls `project_goal_progress` from Plan-01 helper, returns `json.dumps(result)`

`prompts/smart_agent.md` — two changes:
1. Line ~181: directional-only restriction replaced with conditional — cite computed number+gap when `get_goal_projection` data is available, directional-only fallback when no data
2. New `get_goal_projection(facet)` tool description in TRAINING & ATHLETIC COACHING section: names 5 valid facets, states numbers are computed server-side, D-02 behind-framing (gap + one rec + "your call, Sir"), on-track does not prescribe

`tests/test_tool_registration_phase25.py` — 5 TDD tests covering all four registration sites + handler callable, written RED before implementation.

## TDD Gate Compliance

- RED commit: `29b1557` — `test(25-02): add failing Phase-25 tool registration tests (RED)` — all 5 fail because `get_goal_projection` not yet registered
- GREEN commit: `b613a84` — `feat(25-02): add core/pace_history.py + register get_goal_projection (GREEN)` — all 5 pass; 9 phase23 regression tests still pass

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| `python3 -m pytest tests/test_tool_registration_phase25.py -x` exits 0 | PASS |
| `python3 -m pytest tests/test_tool_registration_phase23.py -x` exits 0 | PASS |
| `grep -c "get_goal_projection" prompts/smart_agent.md` >= 1 | PASS (2) |
| "projection — directional only" no longer present | PASS |
| `grep -n "Asia/Jerusalem" core/tools.py` shows handler tz-correct today_iso | PASS |
| No "date.today()" in `_handle_get_goal_projection` | PASS |
| `grep -c "avg_pace" core/pace_history.py` = 0 in SQL (only in comment) | PASS |
| facet validation against `_BENCHMARK_FACETS` before any store access | PASS |
| threshold_pace prefers dense Garmin history, falls back to BenchmarkStore when empty | PASS |
| get_goal_projection excluded from WORKER_TOOL_SCHEMAS (T-25-08) | PASS |

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1: TDD RED — failing tests | 29b1557 | tests/test_tool_registration_phase25.py |
| Task 2: TDD GREEN — pace_history + tool registration | b613a84 | core/pace_history.py, core/tools.py |
| Task 3: smart_agent.md prompt update | c782efa | prompts/smart_agent.md |

## Deviations from Plan

None — plan executed exactly as written. The PATTERNS.md note about adding the tool description "near the existing get_benchmark_history usage description" was applied to the TRAINING & ATHLETIC COACHING section since `get_benchmark_history` had no explicit description there; the new block is the first such description and explicitly names all six brain-direct block/benchmark tools.

## Known Stubs

None — `get_goal_projection` is a complete, wired handler that calls `project_goal_progress` (Plan-01 helper) with real Firestore and Postgres data sources.

## Threat Flags

None. No new network endpoints, no new auth paths, no new schema changes. The handler uses only existing Firestore stores and an existing Postgres read path.

## Self-Check: PASSED

- `core/pace_history.py` exists: FOUND
- `tests/test_tool_registration_phase25.py` exists: FOUND
- Commit 29b1557 (RED): FOUND
- Commit b613a84 (GREEN): FOUND
- Commit c782efa (prompt): FOUND
- All 5 phase25 tests pass: CONFIRMED
- All 9 phase23 tests pass: CONFIRMED (no regression)
