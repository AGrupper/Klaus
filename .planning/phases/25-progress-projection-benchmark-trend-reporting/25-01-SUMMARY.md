---
phase: 25-progress-projection-benchmark-trend-reporting
plan: "01"
subsystem: core/projection
tags: [pure-function, tdd, projection, PROG-02, benchmark, trend]
dependency_graph:
  requires: []
  provides: [core/projection.py::project_goal_progress, FACET_DIRECTION, GOAL_METRIC_TO_FACET]
  affects: [core/tools.py, core/weekly_training_review.py]
tech_stack:
  added: []
  patterns: [linear-LSQ, dataclass+asdict, today_iso-parameter-CR01, try/except-fail-open]
key_files:
  created:
    - core/projection.py
    - tests/test_projection.py
  modified: []
decisions:
  - "Linear LSQ via stdlib sum() arithmetic (no scipy/numpy) — appropriate for sparse ≤3-point data"
  - "Dedup history by date before LSQ fit — keeps most recent value per date (Pitfall 2)"
  - "threshold_pace target resolved via _hm_to_sec_per_km('1:25:00') → 241.7 sec/km"
  - "_FACET_TO_METRIC reverse dict derived from GOAL_METRIC_TO_FACET at import time"
metrics:
  duration_seconds: 183
  completed_date: "2026-06-08"
  tasks_completed: 2
  files_created: 2
  tests_added: 8
---

# Phase 25 Plan 01: Deterministic Projection Helper Summary

**One-liner:** Pure-function `project_goal_progress` with linear-LSQ trend, 3 confidence branches (no_data/baseline_only/projected), direction-aware on_track, and HM-time-string-to-sec/km conversion.

## What Was Built

`core/projection.py` — a stdlib-only, zero-I/O projection helper that takes a benchmark history list, dated goals, and a caller-supplied `today_iso` string, and returns a JSON-serializable `ProjectionResult` dict. The module exposes:

- `FACET_DIRECTION` — maps each of the 5 benchmark facets to higher/lower-is-better
- `GOAL_METRIC_TO_FACET` — maps dated_goals.metrics keys to BenchmarkStore facet names
- `project_goal_progress(facet, history, dated_goals, today_iso) -> dict`

`tests/test_projection.py` — 8 unit tests covering all PROG-02-A through PROG-02-G and PROG-02-N, written first (RED) before the implementation (GREEN). No Firestore mocks needed — pure-function under test.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| LSQ via plain Python sum() — no external math libs | Sparse data (≤3 pts typical); stdlib only, no new dependency |
| `today_iso` parameter — never calls `date.today()` | CR-01 tz lesson from Phase 24; the Sunday cron runs at 10:00 Israel = 07:00 UTC |
| `den != 0` guard in `_linear_project` | Pitfall 2: same-date dedup prevents ZeroDivision; guard is belt-and-suspenders |
| Dedup history by date before fit | BenchmarkStore doc IDs are `{date}_{facet}` (idempotent), but get_facet_history could return two entries with same date from different blocks in theory |
| Confidence: "low" (2 pts), "medium" (3 pts), "high" (4+ pts) | D-01 — confidence_label names the count for transparency |
| _hm_to_sec_per_km parses H:MM:SS and divides by 21.1 | "1:25:00" → 5100s / 21.1 ≈ 241.7 sec/km; within 0.5 tolerance per test |
| try/except wraps entire body, returns no_data on any error | T-25-01 mitigation; malformed today_iso or unexpected input fails safe |

## TDD Gate Compliance

- RED commit: `f7230a3` — `test(25-01): add failing tests for project_goal_progress (RED)` — collection error on missing `core.projection` import confirmed
- GREEN commit: `ef9c223` — `feat(25-01): implement core/projection.py pure-function helper (GREEN)` — all 8 tests pass

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| `python3 -m pytest tests/test_projection.py -x` exits 0 (all 8 pass) | PASS |
| `grep -v '^#' core/projection.py \| grep -c 'date.today\|datetime.now'` → 0 in code (2 in docstrings only — AST scan confirmed no actual calls) | PASS |
| `core/projection.py` imports only stdlib (`__future__`, `logging`, `dataclasses`, `datetime`, `typing`) | PASS |
| Direction-aware on_track: higher-is-better and lower-is-better both correct | PASS |
| HM time "1:25:00" → 241.7 sec/km within 0.5 tolerance | PASS |
| 0-point facets return projected_value=None (no invented convergence) | PASS |

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1: TDD RED — failing tests | f7230a3 | tests/test_projection.py |
| Task 2: TDD GREEN — implementation | ef9c223 | core/projection.py |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `core/projection.py` is a complete pure-function implementation. All 5 facets resolve targets from real `dated_goals` structures matching the verified Firestore shape.

## Threat Flags

None. No new network endpoints, no new auth paths, no new schema changes. The module is read-only / pure-function and accesses no external systems.

## Self-Check: PASSED

- `core/projection.py` exists: FOUND
- `tests/test_projection.py` exists: FOUND
- Commit f7230a3 (RED): FOUND
- Commit ef9c223 (GREEN): FOUND
- All 8 tests pass: CONFIRMED (0.01s run time)
