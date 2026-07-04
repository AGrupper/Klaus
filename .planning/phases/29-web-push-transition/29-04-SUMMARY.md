---
phase: 29-web-push-transition
plan: 04
subsystem: infra
tags: [pywebpush, vapid, web-push, secret-manager, firestore]

# Dependency graph
requires:
  - phase: 29-web-push-transition (plan 01)
    provides: VAPID_PUBLIC_KEY env var + klaus-vapid-private-key Secret Manager secret
  - phase: 29-web-push-transition (plan 03)
    provides: PushSubscriptionStore (memory/firestore_db.py) — list_all/delete/record_success/record_failure
provides:
  - "core/push_sender.py::send_push_to_all — the single sync Web Push fan-out primitive every send path calls via run_in_executor"
  - "CLASS_TTL dict (D-07 per-message-class TTL)"
  - "_get_vapid_private_key — Secret Manager load, cached module-level"
affects: [29-06, 29-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sync external POST fan-out wrapped for run_in_executor (weekly-review-500 class avoidance)"
    - "Fresh vapid_claims dict constructed per-iteration (pywebpush mutates its input in place)"

key-files:
  created:
    - core/push_sender.py
    - tests/test_push_sender.py
  modified: []

key-decisions:
  - "Payload body truncated to text[:1000] as a documented, justified deviation from D-12's literal 'full message text' — APNs caps encrypted push payloads at ~4KB (RESEARCH A8); full text always remains available via the Firestore conversation store + Telegram mirror."
  - "VAPID key load mirrors core/auth_google.py::SecretManagerTokenStorage's access_secret_version call shape exactly, for consistency with the existing Secret Manager access pattern in the codebase."
  - "_get_subscription_store follows the core/tools.py::_get_task_store lazy-singleton-per-call convention (env-driven GCP_PROJECT_ID/FIRESTORE_DATABASE, lazy import for module-cheap-import discipline)."

patterns-established:
  - "Sync webpush() call always carries an explicit timeout=10 and a fresh vapid_claims dict per iteration — future push-sending code (if any) should follow this shape."

requirements-completed: [PUSH-02]

# Metrics
duration: 6min
completed: 2026-07-04
---

# Phase 29 Plan 04: Web Push Sender Summary

**Synchronous VAPID-authenticated Web Push fan-out (`core/push_sender.py::send_push_to_all`) with per-message-class TTL and 404/410 subscription cleanup, fully covered by mocked-`pywebpush` unit tests.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-04T10:12:34+03:00 (base commit)
- **Completed:** 2026-07-04T10:17:32+03:00
- **Tasks:** 1 completed (TDD: RED + GREEN)
- **Files modified:** 2 (both created)

## Accomplishments
- `core/push_sender.py::send_push_to_all(text, message_class="default")` — the single sync push-sending primitive that every future async caller (Plans 06/08) will invoke via `loop.run_in_executor`
- VAPID private key lazily loaded from Secret Manager (`klaus-vapid-private-key`) once per process, cached in a module-level var, never logged or returned
- `CLASS_TTL` dict with the exact D-07 values (`leave_by`/`habit_nudge` = 3600s; `chat_reply`/`briefing`/`review`/`alert`/`default` = 86400s)
- Per-subscription classification: success → `record_success`; 404/410 → `delete`; any other `WebPushException` status or generic exception (DNS/timeout) → `record_failure`
- Fresh `vapid_claims` dict constructed on every iteration (pywebpush mutates the dict it's given — sharing one across sends would corrupt later sends)
- 13 mocked-`webpush` unit tests covering CLASS_TTL values, payload shape/truncation, all four outcome branches, fresh-claims-per-send, mixed multi-subscription fan-out, and Secret-Manager load+cache

## Task Commits

TDD cycle for Task 1 (`send_push_to_all`):

1. **RED** - `b8e3c29` (test) - `test(29-04): add failing tests for send_push_to_all fan-out` — 13 tests written against the not-yet-existing module; confirmed `ModuleNotFoundError` before any implementation existed
2. **GREEN** - `e2a2aef` (feat) - `feat(29-04): implement send_push_to_all sync push fan-out` — implementation added; all 13 tests pass

No REFACTOR commit needed — implementation was correct on first pass.

**Plan metadata:** (SUMMARY.md commit, made by orchestrator per worktree convention — not committed by this agent)

## Files Created/Modified
- `core/push_sender.py` - `send_push_to_all` fan-out, `CLASS_TTL`, `_get_vapid_private_key` (Secret Manager, cached), `_get_subscription_store` (lazy PushSubscriptionStore accessor)
- `tests/test_push_sender.py` - 13 tests: CLASS_TTL values, payload shape/truncation, success/404/410/500/generic-exception branches, fresh-claims-per-send, mixed fan-out, Secret Manager load+cache

## Decisions Made
- Truncating the push body to `text[:1000]` is a documented, justified deviation from D-12's literal "full message text" spec — see `key-decisions` above. Full text is never lost (conversation store + Telegram mirror retain it).
- No other deviations — implementation follows the RESEARCH.md Pattern 5 sketch and the `SecretManagerTokenStorage`/`_get_task_store` analogs almost verbatim.

## Deviations from Plan

None - plan executed exactly as written (the text[:1000] truncation was already called out in the plan itself as a pre-approved, documented deviation from D-12, not a new deviation introduced during execution).

## Issues Encountered
None. `pywebpush` 2.3.0 and `google-cloud-secret-manager` were both already installed and importable per the Wave 1 setup notes; no package installs were needed.

## TDD Gate Compliance

Both gates present in git log for this plan:
1. `test(29-04): add failing tests for send_push_to_all fan-out` (`b8e3c29`) — RED, confirmed failing (`ModuleNotFoundError`) before implementation existed
2. `feat(29-04): implement send_push_to_all sync push fan-out` (`e2a2aef`) — GREEN, all 13 tests pass

No REFACTOR commit — not needed.

## User Setup Required

None - no external service configuration required. VAPID secret (`klaus-vapid-private-key`) and `GCP_PROJECT_ID`/`FIRESTORE_DATABASE` env vars already exist per Wave 1 setup notes.

## Next Phase Readiness
`send_push_to_all` is ready for Plan 08 (send paths: crons, briefings, autonomous tick) and Plan 06 (hub-reply hook) to wire in via `loop.run_in_executor(None, send_push_to_all, text, message_class)`. No blockers.

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-04*

## Self-Check: PASSED

- FOUND: core/push_sender.py
- FOUND: tests/test_push_sender.py
- FOUND commit: b8e3c29 (test)
- FOUND commit: e2a2aef (feat)
