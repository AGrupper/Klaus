---
phase: 29-web-push-transition
plan: 05
subsystem: api
tags: [firestore, brain-direct-tools, heartbeat, push, telegram-mirror]

# Dependency graph
requires:
  - phase: 29-web-push-transition (Plan 03)
    provides: PushSubscriptionStore + HubSettingsStore (Firestore) in memory/firestore_db.py
provides:
  - toggle_telegram_mirror brain-direct tool (D-11 conversational Telegram-retirement path)
  - get_push_health brain-direct tool (subscription/mirror self-awareness, D-13)
  - _check_push_health heartbeat checker (mirror-aware severity, D-14 self-validation)
affects: [29-08 (heartbeat/scheduled_message integration), 29-transition-review]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Brain-direct tool 3-part registration (schema + SMART_AGENT_DIRECT_TOOLS frozenset + _HANDLERS), modeled on get_self_status"
    - "Heartbeat checker returns list[Signal], registered in the every-tick _collect_signals tuple (not weekly-only)"

key-files:
  created: []
  modified:
    - core/tools.py
    - core/heartbeat.py
    - tests/test_tools.py
    - tests/test_heartbeat.py

key-decisions:
  - "get_push_health omits chat_visible_until — that D-02 gate is an in-process variable in core/scheduled_message.py (Plan 08), so a Firestore-sourced field would always read null and mislead Klaus's self-awareness"
  - "get_push_health only surfaces user_agent/last_success_at/failure_count per device — p256dh/auth encryption keys and the VAPID key are never included (T-29-09 mitigation)"
  - "push:no-subscription severity is warning while telegram_mirror_enabled is True, critical when False — Telegram still covers delivery during the mirror week (D-14)"
  - "push:delivery-stale checked only when push_enabled_at is set AND subscriptions exist, to avoid noise before rollout"

patterns-established:
  - "Pattern 9 (RESEARCH.md): brain-direct push tools + heartbeat checker, mirror-aware severity"

requirements-completed: [PUSH-03]

# Metrics
duration: 25min
completed: 2026-07-04
---

# Phase 29 Plan 05: Push Self-Awareness Tools + Heartbeat Checker Summary

**Klaus can flip the Telegram-mirror flag and report push subscription health via two brain-direct tools, and the heartbeat now surfaces push-failure signals with mirror-aware severity — all via TDD RED/GREEN commits.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-04T06:57:00Z
- **Completed:** 2026-07-04T07:22:00Z
- **Tasks:** 2 (both `tdd="true"`)
- **Files modified:** 4 (core/tools.py, core/heartbeat.py, tests/test_tools.py, tests/test_heartbeat.py)

## Accomplishments

- `toggle_telegram_mirror(enabled)` and `get_push_health()` registered as brain-direct tools (schema + `SMART_AGENT_DIRECT_TOOLS` + `_HANDLERS`), reachable via `get_smart_schemas()` — Amit can say "kill the mirror" and Klaus executes it with one tool call
- `get_push_health()` reports subscription count, per-device `user_agent`/`last_success_at`/`failure_count`, `telegram_mirror_enabled`, and `push_enabled_at` — with encryption keys and `chat_visible_until` deliberately excluded
- `_check_push_health()` heartbeat checker covers all three RESEARCH Pattern 9 conditions (failure streak, no-subscription, delivery-stale) and runs every tick via `_collect_signals`

## Task Commits

Each task followed the plan's TDD RED → GREEN cycle:

1. **Task 1: toggle_telegram_mirror + get_push_health brain-direct tools**
   - `ae80b6c` test(29-05): add failing tests for push self-awareness tools (RED)
   - `c4f2fee` feat(29-05): add toggle_telegram_mirror + get_push_health brain-direct tools (GREEN)
2. **Task 2: _check_push_health heartbeat checker**
   - `a3ee0f0` test(29-05): add failing tests for _check_push_health heartbeat checker (RED)
   - `90d65ee` feat(29-05): add _check_push_health heartbeat checker (GREEN)

## Files Created/Modified

- `core/tools.py` - Added `toggle_telegram_mirror`/`get_push_health` schemas, frozenset entries, `_handle_toggle_telegram_mirror`/`_handle_get_push_health` handlers, `_HANDLERS` entries
- `core/heartbeat.py` - Added `_parse_push_timestamp` helper + `_check_push_health()` checker, registered in the `_collect_signals` every-tick checker tuple
- `tests/test_tools.py` - `TestPushSelfAwarenessTools` (11 tests): registration sites, schema shape, handler behavior, key-redaction assertion
- `tests/test_heartbeat.py` - 7 new tests: failure-streak, no-subscription mirror-aware severity (both branches), no-signal-pre-rollout, delivery-stale (both branches), checker-tuple registration

## Decisions Made

- Followed the plan's exact field selection for `get_push_health` — no `chat_visible_until` (D-13 rationale: would always read stale/null from Firestore since that gate lives in-process in `core/scheduled_message.py`, built in Plan 08)
- `_check_push_health` reuses `_jsonsafe_doc`-emitted ISO strings from `PushSubscriptionStore.list_all()` for `last_success_at`; added a small `_parse_push_timestamp` helper defensive against a raw `datetime` slipping through (matches the existing `check_cron_health` tz-handling pattern)
- Condition-3 (delivery-stale) gated on `push_enabled_at` truthy AND subscriptions existing, so it doesn't fire noise before push rollout or double up with condition 2

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched their `<action>` blocks precisely (schema wording, handler signatures, fingerprint formats, severity table).

## Issues Encountered

None. `core/push_sender.py` (built in parallel Plan 04) was not referenced by this plan — no cross-worktree dependency issue.

## User Setup Required

None - no external service configuration required. This plan only adds brain-accessible Firestore reads/writes on top of the already-deployed `PushSubscriptionStore`/`HubSettingsStore` (Plan 03).

## Next Phase Readiness

- `toggle_telegram_mirror` and `get_push_health` are ready for Klaus to use in conversation once Plan 03's stores are populated by real subscriptions (Plan 04's `core/push_sender.py` writes `last_success_at`/`failure_count`)
- `_check_push_health` will start emitting real signals once `push_enabled_at` is stamped (expected to land via the frontend settings flow, separate plan) and devices subscribe
- No blockers for Plan 08 (scheduled_message.py integration) or the eventual D-11 mirror-retirement conversation

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-04*
