---
phase: 26-hub-shell
plan: 02
subsystem: backend
tags: [firestore, morning-briefing, itsdangerous, pytest, testing]

requires:
  - phase: 25-living-plan
    provides: existing SelfStateStore / UserProfileStore Firestore stores + morning_briefing compose
provides:
  - session_version + telegram_user_id scaffold fields on UserProfileStore (D-02 sign-out-everywhere + hub→Telegram identity bridge)
  - dated daily_note written best-effort by the morning briefing (TIME-07 coach-note source)
  - itsdangerous>=2.2 pinned in requirements.txt (signed hub session cookies)
  - three Wave-1 backend test scaffolds (auth / api_today / hub_chat) as a Nyquist anchor
affects: [26-03, 26-04, 26-05]

tech-stack:
  added: [itsdangerous>=2.2]
  patterns: [skip-marked test scaffolds that downstream plans flip to real assertions]

key-files:
  created:
    - tests/test_firestore_hub_fields.py
    - tests/test_hub_auth.py
    - tests/test_api_today.py
    - tests/test_hub_chat.py
  modified:
    - memory/firestore_db.py
    - core/morning_briefing.py
    - requirements.txt

key-decisions:
  - "Coach-note source = SelfStateStore daily_note + daily_note_date (RESEARCH option 1); /api/today serves None when daily_note_date != today."
  - "daily_note write wrapped in try/except logged WARNING so it can never block the morning briefing send."
  - "Hub keys FirestoreConversationStore on telegram_user_id (default None) — the hub→Telegram identity bridge (RESEARCH Open Question 2)."

patterns-established:
  - "Wave 0 test scaffolds: named, skip-marked stubs that import cleanly so no downstream task runs 3-deep without an automated verify anchor."

requirements-completed: [HUB-01, TIME-07, CHAT-01]

duration: ~6min
completed: 2026-06-15
---

# Phase 26 Plan 02: Backend Data Foundation Summary

**Added the hub→Telegram identity bridge + sign-out-everywhere scaffold fields, a dated coach-note written by the morning briefing, the itsdangerous pin, and the four Wave-1 backend test anchors.**

## Performance

- **Duration:** ~6 min (executor truncated by session limit after Task 1–2 + partial Task 3; orchestrator completed Task 3 inline)
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files modified:** 7 (3 created by executor + 1 created inline; 3 modified)

## Accomplishments
- `UserProfileStore._SCAFFOLD` now carries `session_version: 0` (D-02 sign-out-everywhere control) and `telegram_user_id: None` (hub→Telegram identity bridge).
- Morning briefing best-effort-writes `daily_note` + `daily_note_date` to `SelfStateStore` after composing — the real source for TIME-07's hub coach note.
- `itsdangerous>=2.2` pinned in `requirements.txt` for HMAC-signed hub session cookies (never relied on transitively).
- Three Wave-1 backend test files seeded with the 12 named, skip-marked stubs from RESEARCH § Validation Architecture so every downstream backend task has an automated verify anchor.

## Task Commits

1. **Task 1: Add hub fields + pin itsdangerous (TDD)** — `7968af9` (test, RED) → `19c24b7` (feat, GREEN)
2. **Task 2: Write daily_note from morning briefing** — `1f91b5f` (feat)
3. **Task 3: Seed Wave 0 backend test scaffolds** — `1e309d9` (test)

## Files Created/Modified
- `memory/firestore_db.py` — added `session_version` + `telegram_user_id` to `UserProfileStore._SCAFFOLD`.
- `core/morning_briefing.py` — best-effort `SelfStateStore.set({daily_note, daily_note_date})` after compose, try/except WARNING.
- `requirements.txt` — `itsdangerous>=2.2` pin.
- `tests/test_firestore_hub_fields.py` — 3 store-field tests (Task 1, green).
- `tests/test_hub_auth.py`, `tests/test_api_today.py`, `tests/test_hub_chat.py` — 12 skip-marked Wave-1 scaffolds.

## Decisions Made
See key-decisions in frontmatter — coach-note source, best-effort write isolation, and the identity bridge field.

## Deviations from Plan

### Execution-recovery deviation (not a code/scope change)

**1. Executor truncated by session limit mid-Task-3**
- **Found during:** Wave 0 parallel execution — the background executor agent hit the Anthropic session limit after committing Tasks 1–2 and creating `test_hub_auth.py` (uncommitted).
- **Fix:** The orchestrator completed Task 3 inline in the same worktree — created the two remaining scaffolds (`test_api_today.py`, `test_hub_chat.py`), verified all 12 stubs collect + run skipped, then committed Task 3 and this SUMMARY on the worktree branch.
- **Files modified:** `tests/test_api_today.py`, `tests/test_hub_chat.py` (created inline); `test_hub_auth.py` (executor's uncommitted file, committed as-is).
- **Verification:** `pytest tests/test_hub_auth.py tests/test_api_today.py tests/test_hub_chat.py` → 12 collected, 12 skipped, exit 0. `pytest tests/test_firestore_hub_fields.py` → 3 passed.
- **Impact:** No scope change — the plan's Task 3 deliverable was completed exactly as specified.

**Total deviations:** 1 (execution recovery, no scope/code-design change).

## Issues Encountered
None beyond the session-limit truncation handled above.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
Wave 1 unblocked: 26-03 (auth) consumes `session_version`/`telegram_user_id` + `itsdangerous`; 26-04 (`/api/today`) consumes `daily_note`; all three Wave-1 plans inherit their test scaffolds to flip from skip → real assertions.

## Self-Check: PASSED

---
*Phase: 26-hub-shell*
*Completed: 2026-06-15*
