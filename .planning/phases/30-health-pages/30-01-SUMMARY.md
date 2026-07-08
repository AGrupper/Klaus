---
phase: 30-health-pages
plan: 01
subsystem: database
tags: [firestore, postgres, psycopg2, health-data]

# Dependency graph
requires:
  - phase: 23-block-benchmark-tracking
    provides: BenchmarkStore (log_benchmark, get_facet_history, get_block_benchmarks)
  - phase: 19-training-recovery-data-layer
    provides: daily_biometrics Postgres schema + core/recovery_metrics.py reference reader
provides:
  - "BenchmarkStore.get_range(start_date, end_date) — cross-facet date-range read"
  - "core/health_reads.py::fetch_biometric_range(start_date, end_date) — full-column Postgres range reader"
affects: [30-health-pages remaining plans (API routes for training/nutrition/sleep pages)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BenchmarkStore.get_range mirrors get_block_benchmarks: FieldFilter chain + client-side sort (class-local convention, not the module _where helper)"
    - "core/health_reads.py: lazy psycopg2 import, connect_timeout=5 + set_session(readonly=True, autocommit=True) read-only session, parameterized %s SQL, never-raise-return-[] discipline"

key-files:
  created: [core/health_reads.py, tests/test_health_reads.py]
  modified: [memory/firestore_db.py, tests/test_benchmark_store.py]

key-decisions:
  - "BenchmarkStore.get_range uses two chained FieldFilter .where() clauses + Python sort, matching the surrounding class methods (get_facet_history/get_block_benchmarks), not the module-level _where helper used by RunDetailStore/StrengthSessionStore"
  - "fetch_biometric_range lives in a new core/health_reads.py module rather than extending core/recovery_metrics.py — that file is reference-only per plan and must not be modified"
  - "fetch_biometric_range uses the read-only session convention (connect_timeout=5, set_session(readonly=True, autocommit=True)) from mcp_tools/database_tool.py rather than the bare connect() in recovery_metrics.fetch_biometric_rows, as defense-in-depth for a read-only health endpoint"

patterns-established:
  - "Range-query test convention for lazy-imported psycopg2: install a fresh MagicMock into sys.modules['psycopg2'] inside a test wrapped by the isolated_modules fixture, so the stub never leaks into other test files collected later in the same pytest session"

requirements-completed: [HLTH-01, HLTH-03]

duration: 3min
completed: 2026-07-08
---

# Phase 30 Plan 01: Health Data Primitives Summary

**Added BenchmarkStore.get_range (cross-facet Firestore date-range query) and core/health_reads.py::fetch_biometric_range (parameterized Postgres daily_biometrics range reader) — the two missing data-access primitives the Phase 30 health API routes depend on.**

## Performance

- **Duration:** 3 min (commit-to-commit; git log shows 2026-07-08T16:37:58+03:00 → 16:40:20+03:00)
- **Tasks:** 2 completed (+ 1 in-scope test-hygiene fix)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `BenchmarkStore.get_range(start_date, end_date)` returns all 5 facets in one call, newest-first, `[]` on any Firestore error — closes the gap RESEARCH.md flagged (Pitfall 2): previously only `get_facet_history(facet, n)` and `get_block_benchmarks(block_id)` existed, neither of which gives a cross-facet date range.
- `core/health_reads.py::fetch_biometric_range(start_date, end_date)` gives the sleep/recovery page a true arbitrary date-range reader over the full `daily_biometrics` column set (date, resting_hr, hrv_baseline, hrv_overnight, sleep_score, sleep_duration, body_battery_max, training_readiness) — `core/recovery_metrics.py::fetch_biometric_rows` is a "last N days" partial-column reader and was left untouched per the plan.
- Both new readers follow the codebase's never-raise, return-`[]`-on-error discipline and are unit-tested for the exception path.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add BenchmarkStore.get_range across all facets** - `b03dc67` (feat)
2. **Task 2: Create core/health_reads.py Postgres range reader** - `3db889c` (feat)
3. **Test-isolation fix (in-scope, Rule 1)** - `4685c7f` (fix)

## Files Created/Modified
- `memory/firestore_db.py` - Added `BenchmarkStore.get_range(start_date, end_date)` (FieldFilter chain + client-side sort, `_jsonsafe_doc`-wrapped, never raises)
- `core/health_reads.py` (new) - `fetch_biometric_range(start_date, end_date)`, lazy psycopg2 import, read-only session, parameterized SQL, full 8-column dict output
- `tests/test_benchmark_store.py` - 4 new tests selectable via `-k benchmark_get_range` (in-range/newest-first, all-5-facets interleaved, exception → `[]`)
- `tests/test_health_reads.py` (new) - 4 tests selectable via `-k range_reader` (missing-DSN → `[]`, success maps full column set + verifies read-only session + parameterized query, connection failure → `[]`, query failure → `[]`)

## Decisions Made
- Matched `BenchmarkStore`'s existing internal convention (`FieldFilter` + Python sort) rather than the module's `_where` helper, per the plan's explicit instruction and PATTERNS.md guidance, for consistency within the class.
- Added `connect_timeout=5` + `conn.set_session(readonly=True, autocommit=True)` to `fetch_biometric_range` even though the closest single-purpose analog (`recovery_metrics.fetch_biometric_rows`) omits both — the plan's `<action>` explicitly directed this, and both `database_tool.py` and RESEARCH.md's own code example include it as defense-in-depth for a read-only endpoint.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Isolated the psycopg2 sys.modules stub in test_health_reads.py**
- **Found during:** Post-Task-2 verification (running the full two-file test suite together)
- **Issue:** The initial test implementation unconditionally overwrote `sys.modules["psycopg2"]` with a fresh `MagicMock()` in 3 tests with no teardown. Since psycopg2 is genuinely installed in this venv, that stub would silently shadow the real package for any test file collected later in the same pytest session — an order-dependent test-pollution bug of exactly the class the project's `conftest.py::isolated_modules` fixture exists to prevent (and that `tests/test_benchmark_store.py`/`tests/test_ingest_garmin.py` already guard against).
- **Fix:** Added the `isolated_modules` fixture (snapshots/restores `sys.modules`) as a parameter to the 3 tests that install the psycopg2 mock. Verified via a direct subprocess check that `psycopg2` is absent from `sys.modules` after `tests/test_health_reads.py` is imported/run.
- **Files modified:** `tests/test_health_reads.py`
- **Verification:** `pytest tests/test_health_reads.py -x -q` still 4/4 green; `python -c "import tests.test_health_reads; 'psycopg2' in sys.modules"` → `False`
- **Committed in:** `4685c7f`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug fix, test-hygiene only — no production code affected)
**Impact on plan:** No scope creep; the fix only touches test isolation, keeping the new test file consistent with the existing project convention for stubbing lazy-imported native-dependency modules.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `BenchmarkStore.get_range` and `core/health_reads.py::fetch_biometric_range` are ready for the `/api/health/training` and `/api/health/sleep` route plans (per 30-PATTERNS.md's route-composition pattern: `asyncio.gather` + `run_in_executor` wrapping both readers).
- No blockers. `core/recovery_metrics.py` is confirmed unchanged (`git diff --stat` empty) so the existing recovery-deviation signal consumers (morning briefing, autonomous tick) are unaffected.

---
*Phase: 30-health-pages*
*Completed: 2026-07-08*

## Self-Check: PASSED

All created/modified files verified present on disk; all 4 commit hashes (`b03dc67`, `3db889c`, `4685c7f`, `fc9e9fb`) verified present in git log.
