---
phase: 32-unified-situation-ambient-memory
plan: 04
subsystem: training-data
tags: [reconciliation, training-reality, pure-function, tdd, firestore, garmin, hevy]

# Dependency graph
requires:
  - phase: 32-unified-situation-ambient-memory
    provides: (none — Plan 04 has no depends_on; builds on existing core/autonomous.py::_gather_training_evidence and core/nightly_review.py::_planned_workouts_for from prior milestones)
provides:
  - "core.training_checkin.planned_sessions_for(date_iso) — public, neutral-module home for weekly_split-keyed planned AM/PM sessions"
  - "core.training_checkin.build_training_reality(dates, planned_by_date, calendar_by_date, evidence_by_date, self_report_by_date, today_iso) — pure D-01/D-02 reconciler with SC-4 terminal-status idempotency"
affects: [32-07 (wires build_training_reality into autonomous gathers + prompt renders), 33-* (occasion cascade will consume training_reality), 34-write-backs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure reconciliation function pattern: callers inject already-fetched data, no store I/O inside (mirrors compute_recovery_concern's shape)"
    - "D-01 precedence via ordered early-return checks (evidence > self-report > intent), not a fuzzy confidence score — guarantees deterministic terminal status"
    - "Modality normalization bucket (_normalize_modality) to reconcile free-text vocabularies from weekly_split/Garmin/calendar into one comparable set"

key-files:
  created: []
  modified:
    - core/training_checkin.py
    - core/nightly_review.py
    - tests/test_training_checkin.py

key-decisions:
  - "planned_sessions_for kept re-exported from nightly_review.py under its original private name (_planned_workouts_for) so existing internal call sites and tests/test_nightly_review.py's patch.object(nr, \"_planned_workouts_for\", ...) keep working unchanged — no test file outside the plan's files_modified list needed edits"
  - "Added an explicit today_iso: str parameter to build_training_reality (not in the plan's literal signature) — required to distinguish 'missed' (past) from 'planned' (today/future) while staying pure, mirrors compute_recovery_concern's existing today_iso pattern in the same module"
  - "Calendar precedence (D-01: calendar intent > weekly_split intent) implemented via _slot_modality: a Training-calendar event whose start hour falls in a slot's half-day (am < 12:00, pm >= 12:00) overrides the static weekly_split modality for that slot"

patterns-established:
  - "Pattern 1 (Sentinel-on-failure gather isolation) not needed here — build_training_reality itself has no I/O to fail; the Plan 07 gather that calls it will apply that pattern"

requirements-completed: [MEM-04]

# Metrics
duration: ~20min
completed: 2026-07-22
---

# Phase 32 Plan 04: Training Reality Reconciler Summary

**Pure `build_training_reality` reconciler in `core/training_checkin.py` merges planned/calendar/self-report/hard-evidence training sources under an explicit D-01 precedence rule with a proven SC-4 terminal-status ("done" never reverts to "missed") invariant, and `planned_sessions_for` now lives in the neutral module so `core/autonomous.py` never needs to import `core/nightly_review.py`.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-22
- **Tasks:** 2 (Task 2 executed as TDD: RED then GREEN)
- **Files modified:** 3 (`core/training_checkin.py`, `core/nightly_review.py`, `tests/test_training_checkin.py`)

## Accomplishments

- Moved `_planned_workouts_for(date_iso)` out of `core/nightly_review.py` into `core/training_checkin.py` as public `planned_sessions_for(date_iso)`, preserving the acyclic import direction (`autonomous.py → training_checkin.py ← nightly_review.py`) that already holds for `compute_recovery_concern`.
- Added a pure, deterministic `build_training_reality(dates, planned_by_date, calendar_by_date, evidence_by_date, self_report_by_date, today_iso)` implementing the locked D-01 precedence (evidence > self-report > calendar intent > weekly_split intent) and D-02 matching (same date + modality only, never time-of-day/pace/distance).
- Proved the SC-4 "done is never re-asked" invariant with an explicit stale-fact idempotency test: a conflicting/stale self-report ("skipped") for a date+slot is overridden by hard evidence, and repeated calls with the same inputs deterministically return the same terminal `"done"`.
- 10 new tests (TDD RED → GREEN) covering evidence-wins, modality-match exclusivity, time-of-day irrelevance, stale-fact idempotency, past/future default status, self-report completed/skipped paths, rest-slot omission, and per-date output shape.

## Task Commits

Each task was committed atomically (Task 2 as TDD RED → GREEN):

1. **Task 1: Move planned_sessions_for into training_checkin.py; nightly_review re-imports it** - `8609ec0` (refactor)
2. **Task 2 (RED): add failing tests for build_training_reality** - `6779bbd` (test)
2. **Task 2 (GREEN): implement build_training_reality D-01/D-02 reconciler** - `8a382ed` (feat)

_No separate plan-metadata commit — SUMMARY.md is committed as part of this worktree's final commit per parallel-executor protocol._

## Files Created/Modified

- `core/training_checkin.py` - Added `planned_sessions_for` (moved from nightly_review), `_normalize_modality`, `_slot_modality`, `_reconcile_slot_status`, and `build_training_reality`
- `core/nightly_review.py` - `_planned_workouts_for` local definition replaced with `from core.training_checkin import planned_sessions_for as _planned_workouts_for`; all internal call sites unchanged
- `tests/test_training_checkin.py` - Added `TestBuildTrainingReality` (10 tests, all named with a `training_reality` substring so the plan's `-k training_reality` selector picks them all up)

## Decisions Made

- Re-exported `planned_sessions_for` under the original `_planned_workouts_for` name in `nightly_review.py` rather than renaming every internal call site — keeps `tests/test_nightly_review.py` (outside this plan's `files_modified`) green without any edits to that file, since Python resolves the module-global name at call time so `patch.object(nr, "_planned_workouts_for", ...)` still intercepts correctly.
- Added a `today_iso: str` parameter to `build_training_reality` beyond the plan's illustrative signature — a pure function still needs an explicit reference date to classify past-vs-future without reading the wall clock; this mirrors `compute_recovery_concern`'s existing `today_iso` parameter in the same file, so the addition is consistent with an established local pattern rather than a new one.
- `_slot_modality` implements the "calendar may override the template" precedence tier literally: a Training-calendar event's start-hour (before/after noon) determines whether it overrides the am/pm weekly_split modality for that date's slot.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Signature refinement] Added `today_iso` parameter to `build_training_reality`**
- **Found during:** Task 2 (TDD RED phase — writing tests exposed that "missed" vs "planned" classification is impossible without a reference date, and the function must stay pure)
- **Issue:** The plan's illustrative signature (`build_training_reality(dates: list[str], ...)`) has no way to distinguish a past date (→ "missed") from today/future (→ "planned") without either reading the wall clock inside the function (breaking purity) or requiring the caller to pre-sort dates.
- **Fix:** Added an explicit `today_iso: str` parameter, mirroring the existing `compute_recovery_concern(garmin_data, today_iso)` pattern already established in the same module.
- **Files modified:** `core/training_checkin.py`, `tests/test_training_checkin.py`
- **Verification:** All 10 `training_reality`-tagged tests pass; function remains pure (no I/O, no `datetime.now()` call).
- **Committed in:** `6779bbd` (RED test signature), `8a382ed` (GREEN implementation)

---

**Total deviations:** 1 auto-fixed (signature refinement, Rule 1)
**Impact on plan:** Necessary for the function to be both pure and capable of the "missed"/"planned" distinction the plan's own acceptance criteria (e) requires. No scope creep — no new files, no new stores, no architectural change.

## Issues Encountered

None. Task 2's TDD flow required temporarily separating the Task 2 implementation from the Task 1 commit (both were drafted together during initial reading) — split cleanly via a scratch-file move so Task 1 committed alone, then RED tests were written and confirmed failing (`ImportError: cannot import name 'build_training_reality'`) before the implementation was restored for the GREEN commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `build_training_reality` and `planned_sessions_for` are ready for Plan 07 to wire into the autonomous gathers (`_gather_calendar`, `_gather_training_evidence` already return compatible shapes) and into the triage/compose prompt renders (tight vs. wide variants per the research's Pattern 4).
- `core/autonomous.py` still does not import `core/nightly_review.py` — verified via `grep -n "import nightly_review" core/autonomous.py` (no match) and a live three-module import (`core.autonomous`, `core.nightly_review`, `core.training_checkin`) with no `ImportError`.
- No blockers. `TestBuildTrainingReality`'s modality coverage is deliberately scoped to "run"/"lift" (the two the plan's acceptance criteria name explicitly) plus a pass-through for other free-text modalities (mobility/calisthenics/rest) — Plan 07 should revisit whether those additional modalities need dedicated evidence sources before they can ever resolve to "done" (currently they can only resolve via a self-report row with a matching `type`).

---
*Phase: 32-unified-situation-ambient-memory*
*Completed: 2026-07-22*
