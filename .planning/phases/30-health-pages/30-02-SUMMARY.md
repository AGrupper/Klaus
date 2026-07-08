---
phase: 30-health-pages
plan: 02
subsystem: api
tags: [fastapi, health-pages, firestore, postgres, hub]

# Dependency graph
requires:
  - phase: 30-health-pages
    plan: 01
    provides: "BenchmarkStore.get_range, core/health_reads.py::fetch_biometric_range"
  - phase: 26-hub-shell
    provides: "require_hub_session, api_today() composition pattern"
provides:
  - "GET /api/health/training — merged strength+run+benchmark log + block dividers + trend series"
  - "GET /api/health/nutrition — per-day/weekly macro series + missing_dates + targets + slot-adherence grid"
  - "GET /api/health/sleep — HRV/sleep/body-battery series + header_stats + pipeline_active"
  - "core.tools._compute_nutrition_averages / _nutrition_targets_and_protein_ratio — shared nutrition math"
affects: [30-health-pages remaining plans (frontend health pages consume these 3 endpoints)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_resolve_range/_range_bounds allowlist ({7d,30d,90d,1y}) — never int()-parses client range input into date arithmetic"
    - "_weekly_bucket_points — isocalendar-keyed weekly avg/sum bucketing, skips null y-values, shared across all 3 routes for D-07"
    - "_health_nutrition_daily — single per-day MealStore.get_day pass feeding both the macro series and the slot-adherence matrix, TTL-cached via the _routes_cache shape (Pitfall 1)"
    - "_health_sleep_data/_health_sleep_pipeline_active — thin executor-safe wrappers over core.health_reads.fetch_biometric_range (Pitfall 3)"
    - "_hrv_baseline_with_fallback — rolling median of hrv_overnight when the stored hrv_baseline column is sparse, reusing core.recovery_metrics.compute_recovery_deviation's fallback math (Pitfall 5)"

key-files:
  created: [tests/test_health_training_api.py, tests/test_health_nutrition_api.py, tests/test_health_sleep_api.py]
  modified: [interfaces/web_server.py, core/tools.py]

key-decisions:
  - "Shared trend math extracted from core.tools._handle_fetch_nutrition_trend into _compute_nutrition_averages + _nutrition_targets_and_protein_ratio (behavior-preserving refactor, verified against tests/test_nutrition_trend_tool.py) so the chat tool and the new /api/health/nutrition route cannot drift"
  - "Calories target derivation reads a literal `calories` key if present, else derives protein_g*4+carbs_g*4+fat_g*9 from whatever macro-gram keys exist and tags calories_target_derived — matches the live nutrition_targets shape (protein_g_per_kg/protein_g_floor/fiber_g_floor, no literal calories key, per RESEARCH.md Open Question A4)"
  - "Sleep pipeline_active reuses fetch_biometric_range with a maximally wide date bound rather than adding a new SELECT 1 reader to core/health_reads.py — that module was out of this plan's files_modified scope (owned by 30-01)"
  - "hrv_baseline sparsity threshold: fewer than half of in-range rows carrying a stored value triggers the rolling-median-of-hrv_overnight fallback; otherwise the stored column is used as-is"

requirements-completed: [HLTH-01, HLTH-02, HLTH-03]

duration: 5min
completed: 2026-07-08
---

# Phase 30 Plan 02: Health Data API Routes Summary

**Three /api/health/* aggregator routes (training/nutrition/sleep) mirroring the api_today() composition pattern — every chart-ready number (weekly buckets, gap markers, targets, previous-benchmark values) computed server-side, zero client-side math.**

## Performance

- **Duration:** 5 min (commit-to-commit; git log shows 2026-07-08T16:57:36+03:00 → 17:02:05+03:00)
- **Tasks:** 3 completed, no deviations
- **Files modified:** 5 (3 test files created, 2 source files modified)

## Accomplishments

- `GET /api/health/training?range=` — merges `StrengthSessionStore`/`RunDetailStore`/`BenchmarkStore` into one reverse-chronological log tagged by `modality`, plus `BlockStore`-derived block dividers (sequential `block_number` since `BlockStore` stores no number field, and the correct `label` field — not the nonexistent `block_name`), plus two `{x,y}` trend series (`strength_volume`, `run_trend`). Benchmark entries carry a `previous_value` (the prior same-facet result) so drill-down needs no second round-trip.
- `GET /api/health/nutrition?range=` — per-day (or weekly, >90d) macro series for all 5 macros, `missing_dates` (an unlogged day is a gap, never a zero-fill — D-08), range averages, targets (deriving a `calories` target when the profile has none, per RESEARCH.md's resolved Open Question A4), `avg_protein_g_per_kg`, and a slot-adherence grid keyed on slot LABEL only (no clock time ever reaches the wire — CLAUDE.md §6). The macro series and the slot grid derive from a **single** per-day Firestore pass (`_health_nutrition_daily`), TTL-cached for >90d ranges, avoiding the ~730-read-per-request trap RESEARCH.md's Pitfall 1 flagged.
- `GET /api/health/sleep?range=` — HRV/sleep/body-battery `{x,y}` series read via `core.health_reads.fetch_biometric_range`, always `run_in_executor`-wrapped (never a synchronous Postgres call inside `async def` — the exact bug class behind the documented 2026-06-24 weekly-review-500 incident). `pipeline_active` is computed independently of the requested range (true iff the table has EVER had a row) so "cron never ran" and "nothing in this window" render as distinct frontend states. `hrv_baseline` falls back to a rolling median of `hrv_overnight` when the stored column is sparse, reusing `core.recovery_metrics.compute_recovery_deviation`'s own fallback math rather than inventing new rolling-window logic.
- All three routes: allowlisted `range` param (`{7d,30d,90d,1y}` → fixed day count, never `int()`-parsed from client input), `require_hub_session`-gated, `asyncio.gather` + `run_in_executor` composition, `_jsonsafe_doc`-wrapped before `JSONResponse`, and weekly-bucketed via one shared `_weekly_bucket_points` helper for ranges over 90 days (D-07).
- Extracted `_compute_nutrition_averages` / `_nutrition_targets_and_protein_ratio` out of `core.tools._handle_fetch_nutrition_trend` (behavior-preserving — `tests/test_nutrition_trend_tool.py` still 10/10 green) so the chat tool and the new nutrition route share one implementation instead of two that could silently drift (the exact class of bug the 2026-06-09 drifting-numbers incident was about).

## Task Commits

Each task was committed atomically:

1. **Task 1: Range allowlist + training route** — `b3b5232` (feat)
2. **Task 2: Nutrition route (shared trend logic, slot adherence)** — `e34d5e0` (feat)
3. **Task 3: Sleep route with pipeline_active guard** — `4649130` (feat)

## Files Created/Modified

- `interfaces/web_server.py` — added `_VALID_RANGES`/`_resolve_range`/`_range_bounds`/`_weekly_bucket_points` (shared range/bucketing helpers) + `_health_training_*` (4 helpers) + `GET /api/health/training` + `_health_nutrition_*` (5 helpers incl. `_health_nutrition_daily`'s single-pass cache) + `GET /api/health/nutrition` + `_health_sleep_*` (3 helpers) + `GET /api/health/sleep`, all registered before the SPA mount, all behind `require_hub_session`
- `core/tools.py` — extracted `_compute_nutrition_averages` + `_nutrition_targets_and_protein_ratio` from `_handle_fetch_nutrition_trend`; the tool function now calls them instead of inlining the math
- `tests/test_health_training_api.py` (new) — 6 tests: expected keys, reverse-chronological interleave, weekly_bucket selection, 401, block_number/label sequential derivation, benchmark previous_value present/null
- `tests/test_health_nutrition_api.py` (new) — 7 tests: missing_dates never zero-filled, derived calories target, weekly_bucket selection, no slot_time/clock-time leak, 401, shared-math contract, single-pass caching
- `tests/test_health_sleep_api.py` (new) — 8 tests: series+header_stats+pipeline_active-true, empty-table pipeline_active-false, empty-range-but-pipeline-active-true (the Pitfall 4 distinction), weekly_bucket selection, 401, baseline_fallback fires vs stored-column-used, range_reader connection-failure

## Decisions Made

- Matched the `_health_training_benchmarks(facet).get_facet_history(facet, n=1000)` approach rather than adding a new date-scoped facet query — `BenchmarkStore` is a small single-user collection, so streaming a generously-capped history to find the immediately-older same-facet entry is simple and correct; no new store method needed.
- Slot-adherence grid shape is `{"slot_labels": [...], "dates": [...], "grid": [{"slot_label", "cells": [{"date", "hit"}]}]}` — rows-then-cells rather than a flat matrix, matching the D-13 "rows are fueling slots, columns are days" mental model directly and keeping cell objects minimal (`date`+`hit` only, no clock time ever included).
- `_health_sleep_pipeline_active` reuses `fetch_biometric_range` with a `1970-01-01`..`2099-12-31` bound rather than adding a dedicated `SELECT 1 ... LIMIT 1` reader to `core/health_reads.py` — that module was outside this plan's `files_modified` scope (owned by 30-01) and the plan's own action text explicitly permits this alternative ("or reuse the range reader with a wide bound").

## Deviations from Plan

None — plan executed exactly as written. All three tasks' acceptance criteria were satisfied on the first implementation pass; no Rule 1/2/3 fixes were needed.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. (Operator note carried from 30-01/RESEARCH.md: confirm the `klaus-biometric-sync` Cloud Scheduler job is live before UAT'ing the deployed Sleep page — `pipeline_active` will correctly render the "isn't syncing yet" placeholder if it is not, but that is a live-data verification step, not a code gap.)

## Next Phase Readiness

- All three `/api/health/*` endpoints are ready for the frontend health pages (Training/Nutrition/Sleep sub-tabs, chart components) to consume via `react-query` + `apiFetch`.
- `git diff` against the pre-plan base touches only `interfaces/web_server.py` (additive, before the SPA mount) and `core/tools.py` (the two extracted helpers) — no OIDC `/cron|/internal|/trigger` route was modified (HUB-04 invariant verified via diff inspection).
- Full regression sweep run per-file (per project convention — full-suite `pytest tests/` segfaults on grpc/protobuf GC): `test_health_training_api.py`, `test_health_nutrition_api.py`, `test_health_sleep_api.py`, `test_health_reads.py`, `test_benchmark_store.py`, `test_nutrition_trend_tool.py`, `test_api_today.py`, `test_web_server.py`, `test_tools.py`, `test_habit_store.py`, `test_habits_api.py` — all green, zero exclusions.

---
*Phase: 30-health-pages*
*Completed: 2026-07-08*

## Self-Check: PASSED

All 3 new test files verified present on disk; `interfaces/web_server.py` and `core/tools.py` modifications verified present; all 3 commit hashes (`b3b5232`, `e34d5e0`, `4649130`) verified present in `git log --oneline`.
