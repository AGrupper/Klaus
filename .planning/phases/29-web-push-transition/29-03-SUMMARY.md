---
phase: 29-web-push-transition
plan: 03
subsystem: database
tags: [firestore, push-notifications, web-push, hub-settings, store-pattern]

# Dependency graph
requires:
  - phase: 26-hub-shell
    provides: "Firestore store conventions (_jsonsafe_doc, _make_firestore_client, HeartbeatConfigStore/RunDetailStore CRUD skeleton) this plan replicates"
provides:
  - "PushSubscriptionStore — multi-device Web Push subscription registry (upsert/list_all/delete/record_success/record_failure), doc id = sha256(endpoint)[:32]"
  - "HubSettingsStore — runtime telegram_mirror_enabled + push_enabled_at flag at config/hub_settings, default mirror ON"
affects: [29-01, 29-02, 29-04, 29-05, 29-06, 29-07, 29-08, 29-09, 29-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Firestore store CRUD skeleton (RunDetailStore-style): reads never raise (return []/defaults + logger.warning), writes re-raise after logger.error"
    - "Hashed doc id for unsafe/long natural keys: sha256(key).hexdigest()[:32]"
    - "Single-doc settings store (HeartbeatConfigStore-style): get() merges {**DEFAULTS, **stored}, set(patch) merge-writes + updated_at SERVER_TIMESTAMP"

key-files:
  created:
    - tests/test_push_subscription_store.py
    - tests/test_hub_settings_store.py
  modified:
    - memory/firestore_db.py

key-decisions:
  - "PushSubscriptionStore doc id is sha256(endpoint).hexdigest()[:32] — endpoint URLs are too long/unsafe as raw Firestore doc ids, and hashing keeps upsert idempotent per device"
  - "HubSettingsStore has NO chat_visible_until field — D-02 in-hub chat visibility is an in-process module variable in core/scheduled_message.py (single Cloud Run instance), never persisted, per explicit plan instruction overriding the earlier PATTERNS.md draft"

patterns-established:
  - "record_success/record_failure small merge-write pattern (IncidentStore.record_open style) for per-subscription delivery health tracking"

requirements-completed: [PUSH-01, PUSH-03]

# Metrics
duration: 11min
completed: 2026-07-03
---

# Phase 29 Plan 03: Push & Hub-Settings Firestore Stores Summary

**Two new Firestore stores — `PushSubscriptionStore` (multi-device Web Push registry, sha256-hashed doc ids) and `HubSettingsStore` (runtime Telegram-mirror toggle, default ON) — both following the repo's established never-raise-reads/re-raise-writes CRUD convention.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-03T18:57:29+03:00 (base plan commit)
- **Completed:** 2026-07-03T19:08:00+03:00
- **Tasks:** 2 completed
- **Files modified:** 3 (1 source, 2 new test files)

## Accomplishments
- `PushSubscriptionStore` supports idempotent multi-device upsert (keyed on `sha256(endpoint)[:32]`), `list_all()` (json-safe, never raises), `delete(endpoint)`, and `record_success`/`record_failure` delivery-health stamping
- `HubSettingsStore` provides a single-doc runtime settings store (`config/hub_settings`) with `telegram_mirror_enabled` defaulting to `True` (mirror ON, D-08/D-09) and `push_enabled_at`
- Both stores follow the RunDetailStore/HeartbeatConfigStore conventions exactly — reads never raise, writes re-raise, `_jsonsafe_doc` applied to every read that could feed `json.dumps`

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: PushSubscriptionStore**
   - `edcaae9` test(29-03): add failing tests for PushSubscriptionStore (RED)
   - `5384f7a` feat(29-03): add PushSubscriptionStore (multi-device fan-out, D-17) (GREEN)
   - `fc53409` fix(29-03): remove premature HubSettingsStore code from Task 1 commit (see Deviations)
2. **Task 2: HubSettingsStore**
   - `7e45336` test(29-03): add failing tests for HubSettingsStore (RED)
   - `db61fdf` feat(29-03): add HubSettingsStore (telegram-mirror flag, D-08/D-09) (GREEN)

_Net diff across the plan: `memory/firestore_db.py` +166 lines (both classes), 2 new test files, no orphaned or leftover code — the `fc53409` correction commit removed exactly what it added earlier so the final diff is clean._

## Files Created/Modified
- `memory/firestore_db.py` — added `class PushSubscriptionStore` (collection `push_subscriptions`) and `class HubSettingsStore` (collection `config`, doc `hub_settings`)
- `tests/test_push_subscription_store.py` — 9 tests: upsert (doc-id derivation, idempotency, merge, re-raise-on-failure), list_all (json-safe, fail-open), delete (re-raise), record_success/record_failure (merge-write shape)
- `tests/test_hub_settings_store.py` — 6 tests: defaults-on-absent-doc, defaults-on-read-failure, merge-over-defaults, set() merge+updated_at, set() re-raise, set-then-get round trip

## Decisions Made
- Doc id for `PushSubscriptionStore` = `hashlib.sha256(endpoint.encode()).hexdigest()[:32]` — matches the plan's explicit instruction and the PATTERNS.md analog rationale (endpoint URLs are unsafe/too long as raw doc ids)
- `HubSettingsStore._DEFAULTS` intentionally omits `chat_visible_until` even though `29-PATTERNS.md`'s example defaults dict included it — the `29-03-PLAN.md` frontmatter/action block explicitly overrides this (D-02 visibility lives in an in-process variable in `core/scheduled_message.py`, tracked by a later plan, never persisted here). Followed the plan text over the earlier pattern-mapper draft since the plan is the more recent, more specific decision.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected a self-introduced TDD sequencing bug: HubSettingsStore code leaked into Task 1's commit**
- **Found during:** Task 1 (PushSubscriptionStore implementation) — a single Edit call accidentally added both `PushSubscriptionStore` and `HubSettingsStore` class bodies to `memory/firestore_db.py`, and the Task 1 GREEN commit (`5384f7a`) landed with both classes present even though Task 2's RED test for `HubSettingsStore` had not yet been written.
- **Issue:** Violates the per-task RED→GREEN discipline the plan calls for (`tdd="true"` on both tasks) — `HubSettingsStore` existed before any test asserted its behavior.
- **Fix:** Removed the `HubSettingsStore` class body immediately in a follow-up commit (`fc53409`), re-verified `PushSubscriptionStore`'s test suite still passed standalone, then re-implemented `HubSettingsStore` properly under Task 2's own RED (`7e45336`) → GREEN (`db61fdf`) cycle.
- **Files modified:** memory/firestore_db.py
- **Verification:** `pytest tests/test_push_subscription_store.py -x` passed after the removal commit; `pytest tests/test_hub_settings_store.py -x` failed (RED) before Task 2's implementation commit and passed (GREEN) after.
- **Committed in:** fc53409 (correction), 7e45336 (RED), db61fdf (GREEN)

---

**Total deviations:** 1 auto-fixed (process/sequencing correction, no functional impact)
**Impact on plan:** Final code and test coverage exactly match the plan's `must_haves` — no scope creep, no leftover artifacts. The correction only affected commit granularity/TDD gate ordering, not the shipped behavior.

## Issues Encountered
- Default `python3` on this machine resolves to Python 3.14 (per CLAUDE.md/project memory, native grpc/protobuf wheels segfault on 3.14 for this repo). Used the project's existing `.venv` (Python 3.13.12, shared across worktrees since `.venv` isn't a git-tracked path) for every `pytest` invocation instead.

## User Setup Required

None - no external service configuration required. Both stores are pure Firestore CRUD classes; no new env vars, secrets, or cron jobs.

## Next Phase Readiness

- `core/push_sender.py` (a later plan in this phase) can now import `PushSubscriptionStore` and call `list_all()` for its fan-out loop, plus `record_success`/`record_failure` per delivery attempt.
- `core/scheduled_message.py`'s mirror-gate extension can now import `HubSettingsStore` and read `telegram_mirror_enabled` before sending to Telegram.
- `core/tools.py`'s planned `get_push_health` / `toggle_telegram_mirror` brain-direct tools can read/write `HubSettingsStore` and read `PushSubscriptionStore.list_all()` directly.
- No blockers. `pytest tests/test_push_subscription_store.py tests/test_hub_settings_store.py` both green (15/15); spot-checked no regressions in `tests/test_run_detail_store.py`, `tests/test_strength_session_store.py`, `tests/test_firestore_hub_fields.py` (23/23 passing).

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-03*
