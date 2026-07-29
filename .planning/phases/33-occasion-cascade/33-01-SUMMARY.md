---
phase: 33-occasion-cascade
plan: 01
subsystem: database
tags: [firestore, testing, occasion-cascade, action-audit, race-marker]

# Dependency graph
requires: []
provides:
  - "ActionLogStore (D-25 action audit) in memory/firestore_db.py — append/get_recent/undisclosed/mark_disclosed"
  - "OccasionInFlightStore (D-19 race marker) in memory/firestore_db.py — mark/active/clear"
  - "tests/occasion_helpers.py — install_firestore_mock, make_occasion_verdict, make_occasion_situation, SKIP_CAUSES"
affects: [33-02, 33-03, 33-04, 33-05, 33-06, 33-07, 33-08, 33-09, 33-10, 33-11, 33-12, 33-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Write-at-action-time (D-25) as the deliberate inverse of write-after-send (D-10) — two logs, never merged"
    - "Fail-open single-doc marker (OccasionInFlightStore mirrors TickSignatureStore)"
    - "Date-key backward-walk reads for doc-per-date stores (not field-indexed range queries)"
    - "Shared test-fixture module (tests/occasion_helpers.py) as single source of truth for occasion test scaffolding"

key-files:
  created:
    - tests/occasion_helpers.py
  modified:
    - memory/firestore_db.py
    - tests/test_firestore_db.py

key-decisions:
  - "install_firestore_mock() lifted verbatim from tests/test_autonomous.py's private _install_firestore_mock — that file keeps its own copy unchanged so its existing tests do not shift"
  - "tests/occasion_helpers.py carries zero production imports — now_context shape is reproduced locally (mirroring core.autonomous._now_context) rather than importing core.autonomous, so the module is safely importable before install_firestore_mock() runs"
  - "ActionLogStore placed immediately after OutreachLogStore in firestore_db.py so the two write disciplines (send-gated vs write-at-action-time) sit side by side in source"
  - "OccasionInFlightStore placed immediately after TickSignatureStore — closest existing fail-open, single-doc analog"
  - "ActionLogStore.get_recent walks date keys backward from `today` rather than issuing a Firestore range query — this store is doc-per-date, not field-indexed (mirrors the streak-counting date-walk pattern already used for habit streaks)"

patterns-established:
  - "Pattern: date-keyed doc-per-day Firestore store with a backward date-key walk for get_recent (as opposed to TrainingLogStore/StrengthSessionStore's field-indexed range query) — use when the store has no need for a Firestore composite index and days-back is bounded and small"
  - "Pattern: shared test-fixture module per phase (tests/occasion_helpers.py) — install_firestore_mock/make_*_verdict/make_*_situation exported once, imported by every later test file in the phase instead of each file hand-rolling its own copy"

requirements-completed: [OCC-04, OCC-05, OCC-07]

# Metrics
duration: 24min
completed: 2026-07-29
---

# Phase 33 Plan 01: Occasion Cascade Firestore Contracts Summary

**Two new Firestore stores (`ActionLogStore` D-25 action audit, `OccasionInFlightStore` D-19 race marker) plus a shared `tests/occasion_helpers.py` scaffolding module every later Phase 33 test file imports.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-07-29T13:31:00Z
- **Completed:** 2026-07-29T13:55:16Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `ActionLogStore` — per-day audit trail of every Layer-2 calendar/task write, written the moment the write happens and deliberately NOT gated on send success (D-25), the exact inverse of `OutreachLogStore`'s D-10 write-after-send rule. `get_recent`/`undisclosed` never raise and route every entry through `_jsonsafe_doc` so a `DatetimeWithNanoseconds`-shaped value never breaks a downstream `json.dumps` (the MealStore/TrainingLogStore trap, avoided here for `get_recent_decisions`, plan 33-09).
- `OccasionInFlightStore` — single-doc, fail-open D-19 race marker with a self-expiring TTL (default 900s) so a crashed occasion can never permanently mute the `*/20` tick.
- `tests/occasion_helpers.py` — `install_firestore_mock`, `make_occasion_verdict` (with the D-02 `SKIP_CAUSES` taxonomy as a frozenset constant), and `make_occasion_situation` (with an `empty=True` mode for the D-11/OCC-04 empty-gate-bypass tests downstream plans need).

## Task Commits

Each task was committed atomically:

1. **Task 1: Shared occasion test scaffolding module** - `c69382d` (test)
2. **Task 2: ActionLogStore — D-25 action audit, written at action time** - `053124d` (feat)
3. **Task 3: OccasionInFlightStore — D-19 race marker** - `f9d8214` (feat)

_No TDD tasks in this plan — each task is `type="auto"` with tests written alongside the implementation._

## Files Created/Modified
- `tests/occasion_helpers.py` - New shared test scaffolding: `install_firestore_mock`, `make_occasion_verdict`, `make_occasion_situation`, `SKIP_CAUSES`
- `memory/firestore_db.py` - Adds `ActionLogStore` (after `OutreachLogStore`) and `OccasionInFlightStore` (after `TickSignatureStore`)
- `tests/test_firestore_db.py` - Adds `TestActionLogStore` (8 tests) and `TestOccasionInFlightStore` (6 tests), including two small in-memory Firestore fakes (`_ActionLogFakeClient`/`_ActionLogFakeDoc`) that understand ArrayUnion-shaped merge writes, reused across both new test classes

## Decisions Made
- `install_firestore_mock()` is a verbatim lift of `test_autonomous.py`'s private `_install_firestore_mock` — that file's own copy is untouched so its 135 existing tests do not shift underneath it.
- `tests/occasion_helpers.py` carries no production imports at all (not even `core.autonomous`), reproducing the small pure `now_context` computation locally instead — this avoids any import-order hazard where a downstream test imports the helpers module before calling `install_firestore_mock()`.
- `ActionLogStore.get_recent` iterates date keys backward from `today` (bounded small loop) rather than a Firestore range query, because this store is doc-per-date, not field-indexed — mirrors the existing habit-streak backward-walk pattern in `firestore_db.py` rather than `TrainingLogStore`/`StrengthSessionStore`'s `where(...).order_by(...)` range-query shape (those stores index on a `date` field; this one doesn't need to).
- `mark_disclosed` is a documented read-modify-write with an explicit last-writer-wins caveat, accepted because the D-19 in-flight marker enforces one occasion composing at a time in practice.

## Deviations from Plan

None - plan executed exactly as written. All three tasks' acceptance criteria were verified directly (see Issues Encountered for one environment-only note, not a plan deviation).

## Issues Encountered
- The worktree's default `python3` resolves to a global Homebrew Python 3.14 install (not a project venv), which is missing the `tiktoken` package required by `tests/test_token_budget.py`. This plan does not touch `prompts/autonomous_triage.md` or any triage-prompt rendering path, so the validation strategy's "re-run `test_token_budget.py` after any triage-prompt edit" sampling rule does not apply here — noted for awareness, not treated as a blocker or deviation. All tests actually required by this plan (`tests/test_firestore_db.py`, `tests/test_autonomous.py`) ran cleanly against the mocked `google.cloud.firestore` module without needing real GCP credentials or `tiktoken`.

## User Setup Required

None - no external service configuration required. Both stores are pure Firestore contracts with no new env vars, secrets, or Cloud Scheduler changes.

## Next Phase Readiness
- `ActionLogStore` and `OccasionInFlightStore` are ready for plan 33-04 (agentic Layer 2 write-and-disclose), plan 33-09 (`get_recent_decisions` tool), and plan 33-11 (heartbeat D-28 anomaly #4, undisclosed actions) to build against — exact signatures locked per `<interfaces>`, do not rename.
- `tests/occasion_helpers.py` is importable and ready for every later Phase 33 test file (`test_nightly_review.py`, `test_morning_briefing.py`, `test_weekly_training_review.py`, `test_heartbeat.py`, `test_tools.py`, `test_task_dispatch.py`) per the Wave 0 requirements in `33-VALIDATION.md`.
- No blockers or concerns for downstream plans.

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-29*

## Self-Check: PASSED

- FOUND: tests/occasion_helpers.py
- FOUND: memory/firestore_db.py (ActionLogStore, OccasionInFlightStore)
- FOUND: tests/test_firestore_db.py (TestActionLogStore, TestOccasionInFlightStore)
- FOUND: .planning/phases/33-occasion-cascade/33-01-SUMMARY.md
- FOUND commit c69382d (Task 1)
- FOUND commit 053124d (Task 2)
- FOUND commit f9d8214 (Task 3)
