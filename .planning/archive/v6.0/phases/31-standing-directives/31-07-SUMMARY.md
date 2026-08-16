---
phase: 31-standing-directives
plan: 07
subsystem: agent-tools
tags: [firestore, standing-directives, prompt-engineering, gap-closure]

# Dependency graph
requires:
  - phase: 31-standing-directives (31-01, 31-03)
    provides: StandingDirectiveStore (with the pre-existing, orphaned supersede()), set/list/cancel_standing_directive tools, persona-conflict prompt rule
provides:
  - "supersedes param on set_standing_directive wired to StandingDirectiveStore.supersede()"
  - "persona-conflict prompt rule instructing supersede-not-cancel"
affects: [31-verification, 32-unified-situation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional supersede-link param on a capture tool, applied after the primary write (add() then supersede()), mirroring the existing add()-then-cancel() shape"

key-files:
  created: []
  modified:
    - core/tools.py
    - tests/test_tools.py
    - prompts/smart_agent.md

key-decisions:
  - "supersede() is called only when supersedes is truthy and only after add() succeeds, keeping the existing no-supersedes capture path byte-for-byte unchanged"
  - "The handler surfaces a superseded:<bool> key in the returned JSON (rather than raising on a missing old_id) so a stale/wrong old_id from the brain fails soft — the new directive is still captured"

patterns-established:
  - "Gap-closure plans for orphaned store methods: add the reachable param to the existing tool rather than a new tool, when the operation is a natural extension of the same capture call"

requirements-completed: [DIR-05]

# Metrics
duration: 15min
completed: 2026-07-22
---

# Phase 31 Plan 07: Persona-Conflict Supersession Summary

**`set_standing_directive` now accepts an optional `supersedes` id that calls the previously-orphaned `StandingDirectiveStore.supersede()`, and the persona-conflict prompt rule now instructs supersede-not-cancel — closing verification gap 1 (DIR-05/SC-5/D-16).**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-22
- **Tasks:** 2/2 completed
- **Files modified:** 3

## Accomplishments
- `set_standing_directive`'s schema and handler now expose `supersedes` — passing an old directive's id makes the handler call `store.supersede(old_id, new_directive_id)` after `add()`, writing `status="superseded"` + `superseded_by` on the old doc (not `status="cancelled"`).
- Backward compatible: omitting `supersedes` never calls `supersede()` — verified by a dedicated test.
- `prompts/smart_agent.md`'s D-16 persona-conflict rule rewritten to instruct the brain to pass `supersedes=<old id>` instead of new-set + `cancel_standing_directive` the old one, and explicitly forbids cancel-and-recreate for this case.
- `StandingDirectiveStore.supersede()` now has a real production caller (`core/tools.py`), resolving the "0 callers" finding from `31-VERIFICATION.md` gap 1.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add `supersedes` param to set_standing_directive so capture writes superseded_by** - `eedd3e4` (feat)
2. **Task 2: Rewrite the persona-conflict rule to supersede instead of cancel-and-recreate** - `1ea7f10` (docs)

**Plan metadata:** (this commit, pending)

## Files Created/Modified
- `core/tools.py` - `supersedes` property added to `set_standing_directive`'s input_schema; `_handle_set_standing_directive` gained a `supersedes: str | None = None` param that calls `store.supersede(old_id=supersedes, new_directive_id=result["id"])` after `add()` and folds a `superseded: bool` key into the returned JSON when `supersedes` is passed
- `tests/test_tools.py` - `_FakeStandingDirectiveStore` gained a `supersede()` method + `superseded`/`supersede_return` tracking; 3 new tests: writes-link, no-supersedes-no-call, nonexistent-id-does-not-raise
- `prompts/smart_agent.md` - D-16 persona-conflict paragraph rewritten to instruct `supersedes=<old id>` instead of new-set + cancel-old, with an explicit "do NOT cancel-and-recreate" statement

## Decisions Made
- The handler applies `supersede()` strictly after `add()` succeeds and only when `supersedes` is truthy, so the existing no-`supersedes` capture path is byte-for-byte unchanged (backward compatibility requirement from the plan's acceptance criteria).
- A `supersedes` pointing at a non-existent id fails soft: `store.supersede()` returns `False`, the handler folds that into `superseded: false` in the response rather than raising — the new directive capture itself must never be blocked by a bad old-id reference.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Gap 1 (DIR-05/SC-5/D-16) from `31-VERIFICATION.md` is closed: the audit link is chat-reachable and the prompt no longer tells the brain to cancel-and-recreate. Gap 2 (DIR-07/D-13 vetoed anti-lesson) from the same verification report remains open — it is the subject of the sibling gap-closure plan `31-08-PLAN.md` (vetoed anti-lesson), not this plan.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-22*

## Self-Check: PASSED

- FOUND: `.planning/phases/31-standing-directives/31-07-SUMMARY.md`
- FOUND: `eedd3e4` (Task 1 commit)
- FOUND: `1ea7f10` (Task 2 commit)
- FOUND: `fea280d` (summary commit)
