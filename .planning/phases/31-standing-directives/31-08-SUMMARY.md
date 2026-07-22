---
phase: 31-standing-directives
plan: 08
subsystem: agent-directives
tags: [firestore, standing-directives, reflection, veto, anti-lesson, tdd]

# Dependency graph
requires:
  - phase: 31-standing-directives (31-06, 31-07)
    provides: StandingDirectiveStore, standing-directive tools (set/list/cancel), core/reflection.py's status=='vetoed' read guard
provides:
  - StandingDirectiveStore.veto(did) — durable status='vetoed' writer (never hard-delete, cache-invalidating)
  - StandingDirectiveStore.get(did) — never-raises single-doc read exposing origin
  - Origin-aware routing in _handle_cancel_standing_directive (klaus_self -> veto(); user_chat -> cancel())
  - End-to-end test proving the D-13 anti-lesson guard fires on the real reject path
affects: [phase-31-verification, phase-33-occasion-cascade (get_recent_decisions may want to surface veto events)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get-then-update, cache-invalidate, never-hard-delete status transition (matches cancel()/expire()/supersede())"
    - "in-memory fake with real state-transition semantics (class-level shared _docs dict) to exercise a real production path across two independently-constructed store instances in a single test"

key-files:
  created: []
  modified:
    - memory/firestore_db.py
    - core/tools.py
    - tests/test_firestore_db.py
    - tests/test_tools.py
    - tests/test_reflection.py

key-decisions:
  - "veto() modeled exactly on cancel()/expire() (get snapshot -> not-exists returns False -> update({status:'vetoed'}) -> re-raise on other errors -> cache-invalidate -> return True) — no new write shape introduced"
  - "get() added as a cheap never-raises single-doc read so the cancel handler doesn't need a full-collection scan just to check origin"
  - "cancel_standing_directive routing keys strictly on origin=='klaus_self' from store.get() — user_chat directives are unaffected, preserving existing cancel-by-Amit semantics"
  - "Replaced the seeded-status reflection test with one that drives add() -> _handle_cancel_standing_directive() -> run_reflection() through a single in-memory fake with real semantics, proving the guard is reachable rather than dead code"

patterns-established:
  - "Origin-aware write routing at a tool handler: look up the record first (get), then choose the write method based on a field on the record, not on caller-supplied intent"

requirements-completed: [DIR-07]

# Metrics
duration: 6min
completed: 2026-07-22
---

# Phase 31 Plan 08: Vetoed Self-Directive Anti-Lesson (Gap Closure) Summary

**Gave the D-13 anti-lesson guard in `core/reflection.py` a real writer: rejecting a klaus_self standing directive via `cancel_standing_directive` now persists `status='vetoed'` (never hard-deleted) instead of `'cancelled'`, and a new end-to-end test proves reflection actually skips re-proposing it.**

## Performance

- **Duration:** 6 min (14:13 -> 14:19 UTC+3, per-task commit timestamps)
- **Started:** 2026-07-22T11:13:42Z
- **Completed:** 2026-07-22T11:19:07Z
- **Tasks:** 3/3 completed
- **Files modified:** 5

## Accomplishments

- `StandingDirectiveStore.veto()` gives `status='vetoed'` a real production writer — the reflection guard (`status == "vetoed"` at `core/reflection.py:520`) was previously dead code with no path that could ever set that status.
- `_handle_cancel_standing_directive` now looks up the directive's `origin` before deciding the write: rejecting a directive Klaus proposed himself durably vetoes it (anti-lesson, D-13); rejecting a directive Amit stated himself still just cancels it.
- The reflection test that previously asserted on a hand-seeded, unreachable `status='vetoed'` doc now drives the entire real path — add (klaus_self) -> reject via the chat tool handler -> veto -> next reflection run skips the matching proposal — closing verification gap 2 (DIR-07/D-13).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add StandingDirectiveStore.veto() writer + get() single-doc read** - `4cc6279` (feat)
2. **Task 2: Route cancel_standing_directive of a klaus_self directive to veto()** - `c6f9954` (feat)
3. **Task 3: Replace the seeded-status reflection test with a real reject->no-re-propose test** - `8e61fb0` (test)

_No separate REFACTOR commits were needed — each task's implementation was correct and minimal on the first pass._

## Files Created/Modified

- `memory/firestore_db.py` - Added `StandingDirectiveStore.veto(did)` (status='vetoed', get-then-update, cache-invalidate, never hard-delete) and `StandingDirectiveStore.get(did)` (never-raises single-doc read, jsonsafe). Updated the class docstring's read/write method lists.
- `core/tools.py` - `_handle_cancel_standing_directive` now calls `store.get(id)` first; routes to `store.veto(id)` when `origin=='klaus_self'`, `store.cancel(id)` otherwise; returns `{"ok": False}` when the id doesn't exist. Updated the `cancel_standing_directive` tool schema description to document the veto semantics.
- `tests/test_firestore_db.py` - Added 9 tests to `TestStandingDirectiveStore` covering `veto()` (sets status, returns True/False, invalidates cache, re-raises on Firestore error, doc survives via `list_all()`) and `get()` (returns doc dict / None / None-on-error).
- `tests/test_tools.py` - Extended `_FakeStandingDirectiveStore` with `veto()` and `get()` (default: existing `user_chat` doc, preserving prior test behavior). Added 4 tests: klaus_self routes to veto, user_chat routes to cancel, missing id returns `{"ok": false}` without calling either write, both branches idempotent.
- `tests/test_reflection.py` - Added `_RealVetoStandingDirectiveStore`, an in-memory fake with real add/get/veto/cancel/expire/list_active/list_all semantics (class-level shared `_docs` so the tool-handler's and reflection's independently-constructed store instances see the same data). Replaced `test_reflection_vetoed_directive_is_not_re_proposed` to drive the real path end to end instead of hand-seeding `status='vetoed'`.

## Decisions Made

- `veto()` and `get()` are modeled exactly on the existing `cancel()`/`expire()`/`get_run()` (RunDetailStore) patterns already in `memory/firestore_db.py` — no new write/read shape introduced, keeping the store internally consistent.
- Routing in `_handle_cancel_standing_directive` keys strictly on `origin` read from `store.get(id)`, not on any caller-supplied hint — this is the one field the plan's threat model (T-31-08-02) required to gate mis-routing.
- The replacement reflection test uses a real-semantics in-memory fake (not `MagicMock`) so `core.tools._handle_cancel_standing_directive` and `core.reflection.run_reflection` — each of which constructs its own `StandingDirectiveStore` instance — observe the same underlying "Firestore" state via a shared class-level dict. This was necessary to prove the guard is reachable through two independently-constructed instances, matching production reality.

## Deviations from Plan

None - plan executed exactly as written. All three tasks matched the plan's `<action>` and `<behavior>` specs; no Rule 1-4 auto-fixes were needed.

## Verification Results

- `grep -rn '"vetoed"' core/ memory/` now shows both the reflection read (`core/reflection.py:520`) and the new writer (`memory/firestore_db.py:2077`), plus the docstring reference — the gap's "dead guard / no writer" finding is resolved.
- `.venv/bin/python -m pytest tests/test_firestore_db.py -k "veto or standing" -x -q` — 25 passed.
- `.venv/bin/python -m pytest tests/test_tools.py -k standing -x -q` — 23 passed.
- `.venv/bin/python -m pytest tests/test_reflection.py -k "vetoed or re_propose" -x -q` — 1 passed.
- Full per-file runs (no `-k` filter) all green: `test_firestore_db.py` 69 passed, `test_tools.py` 100 passed, `test_reflection.py` 17 passed.
- `core/reflection.py`'s `status == "vetoed"` guard was NOT modified, per the plan's explicit instruction — only the writer was supplied.

## Known Stubs

None.

## Threat Flags

None — this plan closes an existing threat register gap (T-31-08-01) rather than introducing new surface. No new endpoints, auth paths, or schema changes were added beyond the two new `StandingDirectiveStore` methods and the routing branch, both scoped by the plan's own threat model.

## Self-Check: PASSED

- FOUND: `memory/firestore_db.py` (contains `def veto` and `def get` in `StandingDirectiveStore`)
- FOUND: `core/tools.py` (contains origin-routing in `_handle_cancel_standing_directive`)
- FOUND: `tests/test_firestore_db.py`, `tests/test_tools.py`, `tests/test_reflection.py`
- FOUND commit `4cc6279` (Task 1)
- FOUND commit `c6f9954` (Task 2)
- FOUND commit `8e61fb0` (Task 3)
