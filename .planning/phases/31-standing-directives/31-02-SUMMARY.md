---
phase: 31-standing-directives
plan: 02
subsystem: database
tags: [firestore, conversation-history, reflection, timestamps]

# Dependency graph
requires:
  - phase: 26-hub-shell
    provides: FirestoreConversationStore with get/get_full/pop_trailing_assistant
provides:
  - "get_recent_window(user_id, hours=24, max_messages=60) — 24h window read on FirestoreConversationStore, independent of the 6h session-idle timeout"
  - "Per-message ISO ts stamp on every newly appended message (_txn_append)"
affects: [31-standing-directives (Plan 06 reflection learning-loop), 32-unified-situation (ambient-recall tail-prepend, conversation_tail gather)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get_recent_window mirrors the get_full try/except-then-empty shape (GoogleAPICallError → [])"
    - "Legacy/malformed-ts tolerance: keep-by-position instead of KeyError or drop, so old conversation docs never break new reads"

key-files:
  created: []
  modified:
    - memory/firestore_conversation.py
    - tests/test_firestore_conversation.py

key-decisions:
  - "get_recent_window deliberately does not consult session_start_index or the idle timeout — it is a separate, timeout-independent read path from get()"

patterns-established:
  - "Timestamp tolerance pattern: try/except ValueError|TypeError around datetime.fromisoformat, falling back to keep-by-position rather than dropping the message — reusable for any future per-message-ts consumer"

requirements-completed: [DIR-06]

# Metrics
duration: 12min
completed: 2026-07-19
---

# Phase 31 Plan 02: Firestore 24h Conversation Window Summary

**`get_recent_window()` on `FirestoreConversationStore` plus per-message ISO `ts` stamping — fixes live bug B3 where nightly reflection read an empty 6h-bounded session window on most nights**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-19T20:00:00Z
- **Completed:** 2026-07-19T20:12:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_txn_append` now stamps every appended message with `"ts": datetime.now(timezone.utc).isoformat()`
- New `get_recent_window(user_id, hours=24, max_messages=60)` returns the last-24h messages regardless of the 6h session-idle timeout that bounds `get()`
- Legacy (pre-Phase-31) messages without a `ts` field, and messages with a malformed/unparseable `ts`, are tolerated — kept by array position, never `KeyError`'d, never silently dropped
- Result is capped to the last `max_messages` entries

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: Write failing get_recent_window + ts tests** - `1b0b4be` (test)
2. **Task 2: Implement get_recent_window + per-message ts stamping** - `1f3b543` (feat)

_Plan metadata commit for this SUMMARY follows separately per worktree convention._

## Files Created/Modified
- `memory/firestore_conversation.py` - Added `ts` stamping in `_txn_append`; added `get_recent_window()` method
- `tests/test_firestore_conversation.py` - Added 7 new tests covering the 24h-window-vs-6h-timeout distinction, legacy no-ts tolerance, malformed-ts tolerance, max_messages cap, missing-doc case, and ts-stamping on append

## Decisions Made
- Followed the RESEARCH.md reference implementation for `get_recent_window` verbatim (exact same try/except/cutoff/tolerance shape) — no deviation from the researched code example.
- `get_recent_window` intentionally ignores `session_start_index`/idle timeout by design (per plan's `<action>` instruction), verified by a dedicated test that first asserts `get()` returns `[]` under the same idle doc, then asserts `get_recent_window()` still returns the 24h content.

## Deviations from Plan

None - plan executed exactly as written. Implementation matches the `31-RESEARCH.md` § Code Examples reference code verbatim (with docstring wording adjusted to describe delivered behavior).

## Issues Encountered

None for the target files. Note: running the broader test suite in this environment (Python 3.14, per project CLAUDE.md/MEMORY.md notes: "venv must be Python 3.11 or 3.13, NEVER 3.14 — grpc/protobuf native wheels segfault") surfaces pre-existing failures in unrelated files (`tests/test_scheduled_message.py`, `tests/test_hub_chat.py`, `tests/test_router_callback_query.py`) that are present independent of this plan's changes (confirmed these files are untouched by this diff: `git diff 034a171 HEAD --stat` shows only `memory/firestore_conversation.py` and `tests/test_firestore_conversation.py`). Out of scope per the executor's Scope Boundary rule — not fixed, not caused by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `get_recent_window()` is ready for Plan 06's reflection learning-loop fix (`core/reflection.py::_gather_day`) to replace the 6h-bounded `conv_store.get()` read.
- Also ready as the shared dependency for Phase 32's ambient-recall tail-prepend and `conversation_tail` gather job (per RESEARCH.md's architectural map) — no further changes needed to this primitive.
- `pytest tests/test_firestore_conversation.py -x` is green: 13/13 passed, including the 3 pre-existing tests.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-19*
