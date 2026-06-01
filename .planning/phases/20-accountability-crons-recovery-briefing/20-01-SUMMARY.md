---
phase: 20-accountability-crons-recovery-briefing
plan: 01
subsystem: database
tags: [firestore, training-log, session-state, tool-registration, tdd]

# Dependency graph
requires:
  - phase: 19-training-awareness-nutrition-coaching
    provides: "MealStore pattern (merge=True idempotency, date-keyed docs); _make_firestore_client factory; SMART_AGENT_DIRECT_TOOLS/TOOL_SCHEMAS/WORKER_TOOL_SCHEMAS/handlers 5-site registration pattern"
provides:
  - "TrainingLogStore: Firestore collection training_log with log_session (idempotent merge=True), get_recent, get_by_date, get_range"
  - "PendingPromptStore: Firestore collection pending_prompts with soft-TTL get, never-raises set/delete, get_open_note_session"
  - "_pending_expiry() helper for 20h UTC session stamps"
  - "log_training tool registered brain-direct at 5 sites in core/tools.py (LOG-03)"
  - "get_training_history tool registered worker-delegated at 4 sites in core/tools.py (LOG-04)"
affects:
  - "20-02 (training checkin cron) — reads/writes TrainingLogStore + PendingPromptStore"
  - "20-03 (callback dispatch) — reads/writes PendingPromptStore"
  - "20-04 (weekly review) — reads TrainingLogStore.get_recent via get_training_history tool"
  - "20-05 (recovery briefing) — reads TrainingLogStore for recovery concern computation"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TrainingLogStore: stream+Python-filter reads (never raise), merge=True idempotent writes (re-raise)"
    - "PendingPromptStore: never-raise set, soft-TTL get via expires_at ISO field comparison"
    - "_pending_expiry(): module-level helper for consistent 20h UTC session stamping"
    - "Garmin RPE normalisation: rpe > 10 and rpe % 10 == 0 → rpe // 10 (Pitfall 7)"
    - "Tool handler slot injection: slot=manual when not supplied by brain (manual_chat path)"

key-files:
  created:
    - "tests/test_training_log_store.py"
    - "tests/test_pending_prompt_store.py"
    - "tests/test_tool_registration_phase20.py"
  modified:
    - "memory/firestore_db.py"
    - "core/tools.py"

key-decisions:
  - "TrainingLogStore.log_session re-raises on write failure (callers must know Garmin sync failed) — reads never raise"
  - "PendingPromptStore.set never raises (degraded to no follow-up, not a crash)"
  - "Soft TTL of 20h enforced in Python via expires_at ISO comparison — no Firestore TTL policy config needed"
  - "Garmin RPE steps-of-10 normalisation in TrainingLogStore.log_session, not in callers (single responsibility)"
  - "_handle_log_training injects slot=manual when absent — supports manual_chat brain direct calls without event slot"

patterns-established:
  - "Phase 20 TDD gate: RED commit before implementation, GREEN commit after all tests pass"
  - "Tool registration insertion order: Phase 20 tools appended after Phase 19 block (not alphabetised)"
  - "Store placement in firestore_db.py: TrainingLogStore → PendingPromptStore → FollowupStore (Phase 20 new stores before Phase 18 stores)"

requirements-completed: [LOG-01, LOG-02, LOG-03, LOG-04]

# Metrics
duration: 45min
completed: 2026-06-01
---

# Phase 20 Plan 01: Firestore Persistence Layer + Tool Registration Summary

**TrainingLogStore (idempotent training log with RPE normalisation) + PendingPromptStore (soft-TTL session state) in Firestore, plus log_training brain-direct and get_training_history worker-delegated tools registered at all 5 sites in core/tools.py**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-06-01T08:20:00Z
- **Completed:** 2026-06-01T09:06:51Z
- **Tasks:** 3 (3 TDD tasks — each RED→GREEN)
- **Files modified:** 5

## Accomplishments

- TrainingLogStore added to `memory/firestore_db.py` after MealStore — collection `training_log`, doc_id `{date}_{slot}`, idempotent merge=True writes, Pitfall-7 RPE normalisation (Garmin raw 10..100 → 1..10), never-raises reads (get_recent / get_by_date / get_range), re-raises writes
- PendingPromptStore added after TrainingLogStore — collection `pending_prompts`, never-raises set(), soft-TTL get() via expires_at ISO comparison (T-20-02 stale-replay mitigation), get_open_note_session(user_id) for router fallback
- `_pending_expiry(hours=20)` module-level helper for consistent UTC session timestamps
- `log_training` registered brain-direct at all 5 sites: SMART_AGENT_DIRECT_TOOLS frozenset, TOOL_SCHEMAS, WORKER_TOOL_SCHEMAS exclusion, handler function, _HANDLERS dispatch (LOG-03)
- `get_training_history` registered worker-delegated at 4 sites: TOOL_SCHEMAS, WORKER_TOOL_SCHEMAS (included), handler function, _HANDLERS (LOG-04)
- 3 new test files: 42 total tests, all green; zero regressions in existing suite (+11 net passing vs baseline)

## Task Commits

Each TDD task committed with RED then GREEN:

1. **Task 1: RED TrainingLogStore tests** - `545528e` (test)
2. **Task 1: GREEN TrainingLogStore implementation** - `54351aa` (feat)
3. **Task 2: RED PendingPromptStore tests** - `c00b755` (test)
4. **Task 2: GREEN PendingPromptStore implementation** - `cddf7fe` (feat)
5. **Task 3: RED Phase20 tool registration tests** - `6fbddaa` (test)
6. **Task 3: GREEN tool registration implementation** - `fab0991` (feat)

## Files Created/Modified

- `tests/test_training_log_store.py` — 13 tests for TrainingLogStore (write/idempotency/RPE-normalise/reads)
- `tests/test_pending_prompt_store.py` — 16 tests for PendingPromptStore (set/get/TTL/delete/get_open_note_session/_pending_expiry)
- `tests/test_tool_registration_phase20.py` — 13 tests for Phase20 tool registration at all 5 sites
- `memory/firestore_db.py` — TrainingLogStore class (160 lines) + _pending_expiry() helper + PendingPromptStore class (177 lines) inserted before FollowupStore
- `core/tools.py` — log_training + get_training_history at 5 sites: SMART_AGENT_DIRECT_TOOLS, TOOL_SCHEMAS, WORKER_TOOL_SCHEMAS exclusion, handlers, _HANDLERS dispatch (111 lines added)

## Decisions Made

- TrainingLogStore writes re-raise (LOG-01 callers must know sync failed) while reads return [] on error (LOG-02) — matches MealStore.upsert vs get_day discipline
- PendingPromptStore.set() never raises — degraded check-in (no follow-up button) is preferable to a crash at 21:30 cron time
- Garmin RPE normalisation lives in TrainingLogStore.log_session not in callers — single responsibility, consistent regardless of call source
- `_handle_log_training` injects `slot="manual"` when not supplied — supports brain calling log_training from a conversation without a calendar event slot

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Test file `test_tool_registration_phase20.py` required more elaborate sys.modules stubs than the plan's test pattern because `core.auth_google` imports `google_auth_oauthlib` (not installed in dev env). Fixed by stubbing `core.auth_google` as a MagicMock entirely — this follows the same spirit as the Firestore mock pattern in test_meal_store.py.

## Known Stubs

None — no placeholder data or hardcoded empty values. TrainingLogStore and PendingPromptStore are fully implemented Firestore-backed stores. Tool handlers perform real Firestore reads/writes via the stores.

## Threat Flags

None — no new network/auth surface in this plan. TrainingLogStore and PendingPromptStore are internal Firestore writes behind existing OIDC/Telegram-guard boundaries. T-20-02 DoS mitigation (soft TTL) is implemented as required.

## Next Phase Readiness

- TrainingLogStore is ready for Phase 20 Plans 02–05 to write/read training sessions
- PendingPromptStore is ready for Plan 03 (callback dispatch) to store multi-step check-in state
- log_training tool is available for brain-direct logging from Telegram conversations
- get_training_history tool is available for worker-delegated retrieval in weekly review

## Self-Check: PASSED

Files verified:
- `memory/firestore_db.py` — FOUND (TrainingLogStore at line 699, PendingPromptStore at line 874)
- `core/tools.py` — FOUND (log_training at lines 56/756/850/1463, get_training_history at lines 811/1464)
- `tests/test_training_log_store.py` — FOUND (13 tests green)
- `tests/test_pending_prompt_store.py` — FOUND (16 tests green)
- `tests/test_tool_registration_phase20.py` — FOUND (13 tests green)

Commits verified:
- `545528e` — test(20-01): add failing TrainingLogStore tests
- `54351aa` — feat(20-01): implement TrainingLogStore
- `c00b755` — test(20-01): add failing PendingPromptStore tests
- `cddf7fe` — feat(20-01): implement PendingPromptStore
- `6fbddaa` — test(20-01): add failing Phase 20 tool registration tests
- `fab0991` — feat(20-01): register log_training + get_training_history tools

---
*Phase: 20-accountability-crons-recovery-briefing*
*Completed: 2026-06-01*
