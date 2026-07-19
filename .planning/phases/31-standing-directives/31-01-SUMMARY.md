---
phase: 31-standing-directives
plan: 01
subsystem: database
tags: [firestore, standing-directives, read-cache, tdd]

# Dependency graph
requires: []
provides:
  - StandingDirectiveStore (memory/firestore_db.py) — add/list_active/list_all/cancel/supersede/expire
  - standing_directives Firestore collection schema (id, text, origin, context_quote, created_at, status, expires_at, condition_text, superseded_by)
affects: [31-02, 31-03, 31-04, 31-05, 31-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "StandingDirectiveStore modeled 1:1 on FollowupStore (memory/firestore_db.py) — never-raise reads, re-raise writes, uuid4 doc ids"
    - "_READ_CACHE-backed list_active(); every write method calls _cache_invalidate_prefix((\"standing_directives\",))"
    - "Status-transition-only mutation (cancel/supersede/expire) — never hard-delete, matches FollowupStore/OutreachLogStore discipline"

key-files:
  created: []
  modified:
    - memory/firestore_db.py
    - tests/test_firestore_db.py

key-decisions:
  - "StandingDirectiveStore placed as a sibling class immediately after FollowupStore in memory/firestore_db.py, before OutreachLogStore — matches the file's existing store-per-collection ordering"
  - "list_all() is deliberately uncached (history reads are rare, unlike the hot list_active() path read on every chat turn + tick)"
  - "cancel/supersede/expire all use the get-then-update shape (return False on non-existence, re-raise on any other Firestore error) — mirrors FollowupStore.cancel exactly"

patterns-established:
  - "Hybrid expiry field shape (expires_at | condition_text | neither) for DIR-02 — reused verbatim by every future plan's directive-related code"
  - "supersede(old_id, new_directive_id) writes superseded_by + status=superseded on the OLD doc for DIR-05/D-16 persona-conflict resolution"

requirements-completed: [DIR-02, DIR-05]

# Metrics
duration: 9min
completed: 2026-07-19
---

# Phase 31 Plan 01: Standing Directive Store Summary

**StandingDirectiveStore in memory/firestore_db.py — durable, verbatim, never-hard-deleted persistence for Amit's lasting behavioral wishes, modeled 1:1 on FollowupStore with a _READ_CACHE-backed list_active() and DIR-05 supersede chain.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-19T23:10:03+03:00
- **Completed:** 2026-07-19T23:10:55+03:00
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `StandingDirectiveStore` class with full lifecycle: `add`, `list_active`, `list_all`, `cancel`, `supersede`, `expire`
- Hybrid expiry field shape (DIR-02): `expires_at` for dated directives, `condition_text` for event-based ones, both `None` for conditionless directives that persist indefinitely
- `supersede()` writes `superseded_by` + `status="superseded"` on the OLD doc, realizing DIR-05's persona-conflict resolution chain (D-16)
- `list_active()` served from the module-level `_READ_CACHE`; every write (`add`/`cancel`/`supersede`/`expire`) invalidates the `("standing_directives",)` prefix
- Never hard-deletes — every mutation is an auditable status transition (verified: zero `.delete(` calls in the class)
- 17 new tests in `TestStandingDirectiveStore`, full `tests/test_firestore_db.py` suite green (61 passed, no regressions)

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: Write failing TestStandingDirectiveStore tests** - `34a14e7` (test)
2. **Task 2: Implement StandingDirectiveStore** - `cedad11` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `memory/firestore_db.py` - Added `StandingDirectiveStore` class (213 lines), sibling of `FollowupStore`
- `tests/test_firestore_db.py` - Added `TestStandingDirectiveStore` class (267 lines, 17 test methods)

## Decisions Made
- Placed `StandingDirectiveStore` immediately after `FollowupStore` and before `OutreachLogStore` in `memory/firestore_db.py`, matching the plan's `<interfaces>` guidance and the file's existing per-collection-class ordering.
- `list_all()` left uncached (per plan's `<action>` guidance: "uncached; history reads are rare") while `list_active()` is the sole cached read, since it is the hot path read on every chat turn and every 20-minute autonomous tick.
- `cancel`/`supersede`/`expire` all follow the identical get-then-update-then-invalidate shape for consistency and to keep the "never hard-delete" invariant trivially auditable by inspection.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance criteria were met verbatim: RED confirmed via `AttributeError` before implementation, GREEN confirmed via full test pass after, and the existing 44 `firestore_db` tests showed zero regressions.

## Issues Encountered

None. The venv on this machine defaults to Python 3.14 (`python3` on PATH), which per `CLAUDE.md`/project memory causes segfaults in grpc/protobuf-backed tests. Used the project's existing `/Users/amitgrupper/Desktop/Klaus/.venv` (Python 3.13.12) for all `pytest` invocations — no code or config change required, just interpreter selection, so not logged as a deviation.

## User Setup Required

None - no external service configuration required. `standing_directives` is a new Firestore collection but Firestore is schemaless; no migration or console action needed. Firestore auto-indexes the single-field `status` filter used by `list_active()`, so no new composite index is required for this plan (confirmed against 31-RESEARCH.md Assumption A2).

## Next Phase Readiness

`StandingDirectiveStore` is ready to be consumed by:
- **31-02/31-03** (brain-direct tools `set_standing_directive`/`list_standing_directives`/`cancel_standing_directive` in `core/tools.py`)
- **31-04** (`render_standing_directives_block()` shared formatter + `{standing_directives}` chat injection)
- **31-05** (autonomous tick gather + triage Step-0 veto, legacy nightly/morning cron injection)
- **31-06** (reflection learning loop's `origin="klaus_self"` directive proposals via `add()`)

No blockers. The store's schema, cache-invalidation contract, and never-hard-delete discipline are all locked and test-covered — downstream plans can build directly against the public method signatures documented in the class docstring.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-19*
