---
phase: 29-web-push-transition
plan: 06
subsystem: api
tags: [fastapi, web-push, vapid, firestore, hub-session]

# Dependency graph
requires:
  - phase: 29-web-push-transition (29-01)
    provides: VAPID_PUBLIC_KEY env var, pywebpush dependency
  - phase: 29-web-push-transition (29-03)
    provides: PushSubscriptionStore + HubSettingsStore (memory/firestore_db.py)
provides:
  - "POST /api/push/subscribe — validates + upserts a browser Web Push subscription"
  - "GET /api/push/vapid-public-key — serves VAPID_PUBLIC_KEY behind hub session"
  - "GET/PATCH /api/settings — read/toggle telegram_mirror_enabled (D-09)"
  - "D-14 heartbeat anchor: push_enabled_at stamped on first successful subscribe"
affects: [29-04 (push_sender heartbeat integration), 29-09 (frontend push hooks), 29-10 (Settings page)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy per-request store factory (_get_push_store / _get_hub_settings_store) mirroring _get_task_store / _get_habit_store — not a memoized singleton, a thin env-driven constructor"
    - "Raw request.json() body validation (not Pydantic) for PATCH /api/settings so a non-bool value gets an explicit 400 instead of FastAPI's generic 422"

key-files:
  created:
    - tests/test_push_api.py
  modified:
    - interfaces/web_server.py

key-decisions:
  - "push_enabled_at stamped by re-reading HubSettingsStore.get() inside the subscribe handler rather than relying on a separate flag — keeps the D-14 anchor logic colocated with the only write path that can trigger it"
  - "PATCH /api/settings reads the raw JSON body and manually validates telegram_mirror_enabled is a bool, rather than a Pydantic model, to return a precise 400 (T-29-12) instead of a generic 422"

patterns-established:
  - "New /api/* route groups are registered directly before the SPA mount block, following the identical structure of the /api/tasks and /api/habits sections (module-level banner comment + Depends(require_hub_session) + run_in_executor + _jsonsafe_doc)"

requirements-completed: [PUSH-01, PUSH-03]

duration: 25min
completed: 2026-07-04
---

# Phase 29 Plan 06: Push Subscribe + Settings API Summary

**Session-authed `/api/push/subscribe`, `/api/push/vapid-public-key`, and `GET/PATCH /api/settings` routes added to `interfaces/web_server.py`, with input-validated subscription upserts and a one-time `push_enabled_at` stamp for the D-14 heartbeat anchor.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-04T07:00:00Z
- **Completed:** 2026-07-04T07:25:00Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `POST /api/push/subscribe` validates `endpoint.startswith("https://")` and presence of `keys.p256dh`/`keys.auth` (400 otherwise), then upserts via `PushSubscriptionStore.upsert` through `run_in_executor`
- First successful subscribe stamps `HubSettingsStore.set({"push_enabled_at": SERVER_TIMESTAMP})` exactly once; later subscribes leave it untouched — makes the D-14 "push enabled but zero subscriptions" heartbeat condition reachable
- `GET /api/push/vapid-public-key` serves `VAPID_PUBLIC_KEY` behind `require_hub_session`
- `GET /api/settings` returns the hub settings doc (`telegram_mirror_enabled`, `push_enabled_at`) jsonsafe; `PATCH /api/settings` accepts only `telegram_mirror_enabled` (400 on non-bool, other keys ignored) and takes effect immediately (D-09)
- All four routes gated by `Depends(require_hub_session)`; none touch OIDC cron/internal/trigger auth (HUB-04 preserved)

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **RED (both tasks):** `f91c7b8` - test(29-06): add failing tests for push/settings API routes
2. **Task 1: /api/push/subscribe + /api/push/vapid-public-key** - `d625cc4` (feat)
3. **Task 2: GET/PATCH /api/settings** - `1ad25b3` (feat)

**Plan metadata:** committed alongside this SUMMARY (see final commit in this plan's git log).

## Files Created/Modified
- `interfaces/web_server.py` - Added `_get_push_store()` / `_get_hub_settings_store()` lazy accessors, `POST /api/push/subscribe`, `GET /api/push/vapid-public-key`, `GET/PATCH /api/settings`, all registered before the SPA mount
- `tests/test_push_api.py` - 10 tests covering auth-gate 401s, subscribe validation (400 on non-https / missing keys), successful upsert, push_enabled_at stamp-once behavior, vapid-public-key response, settings GET/PATCH round-trip, and PATCH non-bool rejection

## Decisions Made
- `push_enabled_at` stamping happens inline in the subscribe handler (read-then-conditionally-write via `HubSettingsStore.get()`/`.set()`) rather than a separate "first subscribe" flag — single source of truth, no additional store needed
- Chose raw-body validation over a Pydantic model for the settings PATCH so a non-bool `telegram_mirror_enabled` produces an explicit `400 {"error": "telegram_mirror_enabled must be a bool"}` instead of FastAPI's default `422`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The two tasks share a contiguous code region in `interfaces/web_server.py` (Task 2 reuses `_get_hub_settings_store()` added by Task 1); to preserve atomic per-task commits the Task 2 routes were written, then temporarily removed from the working tree so Task 1 could be verified and committed in isolation, then re-added and committed as Task 2 — no functional difference from a single edit, just commit granularity.

## User Setup Required

None - no external service configuration required. `VAPID_PUBLIC_KEY` was already set locally per Wave 1 (29-01); no new env vars introduced.

## Next Phase Readiness

- `/api/push/subscribe`, `/api/push/vapid-public-key`, and `/api/settings` are live and ready for the frontend push-registration hooks (Plan 09) and the Settings page (Plan 10) to consume
- `push_enabled_at` is now reachable for `core/heartbeat.py`'s D-14 push-failure alerting (Plan 04, built in parallel this wave) to read via `HubSettingsStore.get()`
- No blockers

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-04*

## Self-Check: PASSED

- FOUND: interfaces/web_server.py
- FOUND: tests/test_push_api.py
- FOUND: .planning/phases/29-web-push-transition/29-06-SUMMARY.md
- FOUND commit: f91c7b8 (test)
- FOUND commit: d625cc4 (feat Task 1)
- FOUND commit: 1ad25b3 (feat Task 2)
- FOUND commit: d07155e (docs SUMMARY)
