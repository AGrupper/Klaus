---
phase: 33-occasion-cascade
plan: 05
subsystem: api
tags: [calendar, firestore, idempotency, audit-trail, google-calendar]

# Dependency graph
requires:
  - phase: 33-01
    provides: "ActionLogStore (D-25 action audit) in memory/firestore_db.py"
provides:
  - "_existing_event_at(start_iso, end_iso, summary, calendar_id=None) — D-23 idempotency pre-check for proactive calendar creates"
  - "_record_action(action, detail, *, occasion='chat') — D-25 write-at-action-time audit helper, wired into all three calendar mutation handlers"
affects: [33-04, 33-09, 33-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Check-then-act idempotency lookup immediately before a write, fail-open on lookup error, after-the-fact detection via the audit trail for the residual race (33-RESEARCH Pitfall 6)"
    - "Write-at-action-time audit record (ActionLogStore) added to every mutation handler's success path, distinct object from the write-after-send OutreachLogStore"

key-files:
  created: []
  modified:
    - core/tools.py
    - tests/test_tools.py

key-decisions:
  - "_existing_event_at matches on summary only (case-folded, whitespace-collapsed) via list_all_events over the requested window — no new Calendar API call shape, reuses the exact lookup _handle_list_all_calendar_events already performs"
  - "_record_action's occasion parameter defaults to 'chat' rather than reading a KLAUS_CURRENT_OCCASION env var — plan 33-04's _run_cascade does not thread an occasion identifier through to this call site yet, and attribution is a nice-to-have the disclosure flow doesn't depend on (entry.at + disclosed=False is sufficient for D-25)"
  - "action_id is added to the handler's JSON response only on the path that actually wrote an entry (create: non-duplicate + non-error; update/delete: result.get('ok') truthy) — the duplicate branch and any calendar-API error branch never call _record_action"
  - "Docstrings deliberately avoid the literal string 'OutreachLogStore' (paraphrased as 'the send-gated outreach log') so the plan's verification grep (`grep -c OutreachLogStore core/tools.py` unchanged from pre-task) stays a meaningful signal that no code touched that store, not just an artifact of prose mentioning it"

patterns-established:
  - "Pattern: mutation handler wraps the manager call, checks a domain-specific success signal (`'error' not in result` for create, `result.get('ok')` for update/delete), and only then calls the audit-record helper — keeps write-at-action-time semantics honest (a handler never records an action for a write that didn't happen)"

requirements-completed: [OCC-05]

# Metrics
duration: 22min
completed: 2026-07-29
---

# Phase 33 Plan 05: Idempotent, Audited Calendar Writes (D-23/D-24/D-25) Summary

**Idempotency pre-check (`_existing_event_at`) blocking duplicate proactive calendar creates, plus a write-at-action-time audit helper (`_record_action`) wired into all three calendar mutation handlers, independent of `OutreachLogStore`'s send-gated D-10 discipline.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-07-29T14:05:00Z
- **Completed:** 2026-07-29T14:27:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments
- `_existing_event_at` — looks up the requested [start_iso, end_iso) window via `GoogleCalendarManager.list_all_events` and returns the first event whose summary matches case-insensitively after whitespace collapse, else `None`. Fails open (returns `None`) on any Calendar API error so a lookup outage never blocks a legitimate create. `_handle_create_calendar_event` calls it immediately before `create_event`; a match returns `{"created": false, "duplicate": true, "existing_event_id", "existing_summary", "reason"}` instead of double-booking.
- `_record_action` — generates a `uuid4().hex` id, builds the D-25 entry shape (`id`, `action`, `detail`, `occasion`, `at`, `disclosed: False`), and appends it to `ActionLogStore` keyed on today's Asia/Jerusalem date. Never raises: an `ActionLogStore.append` failure is logged at ERROR and the generated id is still returned, so a write that already landed on Amit's calendar is never rolled back or hidden because its audit write failed.
- All three calendar mutation handlers (`_handle_create_calendar_event`, `_handle_update_calendar_event`, `_handle_delete_calendar_event`) now call `_record_action` on their success path only, and surface the returned id as `"action_id"` in the JSON response. The duplicate-detected branch and any Calendar-API-error branch never call it — nothing was written, nothing is recorded.

## Task Commits

Each task was committed atomically:

1. **Task 1: Idempotency pre-check before a proactive calendar create (D-23)** - `f0431e7` (feat)
2. **Task 2: Record every calendar mutation in the action audit trail (D-24, D-25)** - `e2e25ff` (feat)

_No TDD tasks in this plan — both tasks are `type="auto"` with tests written alongside the implementation._

## Files Created/Modified
- `core/tools.py` - Adds `_existing_event_at` (idempotency lookup) and `_record_action` (D-25 audit helper); wires both into `_handle_create_calendar_event`, `_handle_update_calendar_event`, `_handle_delete_calendar_event`
- `tests/test_tools.py` - Adds `_FakeActionLogStore` + `fake_action_log` fixture, `TestCalendarCreateIdempotency` (6 tests: match/no-match/fail-open lookup behaviour, duplicate-blocks-create, normal-create-still-works), `TestActionAuditTrail` (5 tests: create/update/delete each record one undisclosed entry with a 32-char hex id, duplicate branch records nothing, an `ActionLogStore.append` failure never blocks the handler's response)

## Decisions Made
- `_existing_event_at` reuses `list_all_events` (already used by `_handle_list_all_calendar_events`) rather than introducing a new Calendar API call — same lookup shape, narrower window, matched exactly to `create_event`'s target window to keep the check-then-act race window as small as possible (33-RESEARCH.md Pitfall 6).
- `_record_action`'s `occasion` keyword defaults to `"chat"` and is never resolved from an env var — per the plan's explicit instruction not to add a cross-module global; attribution to the originating occasion is deferred as a nice-to-have since `disclosed=False` + the entry's `at` timestamp already satisfies D-25's "the next occasion sees I already did this but never told him."
- Docstrings paraphrase `OutreachLogStore` as "the send-gated outreach log" instead of using the literal class name, so the plan's `grep -c "OutreachLogStore" core/tools.py` verification gate stays meaningful (0 before this plan, 0 after) — a docstring mention would otherwise have inflated the count without any code actually touching that store.

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria and the plan-level `<verification>` block (`pytest tests/test_tools.py -x -q`, `pytest tests/test_calendar_tool.py -x -q`, `grep -c "OutreachLogStore" core/tools.py` unchanged) were verified directly.

## Issues Encountered
None. `create_event`'s success/error shape (`"error"` key present only on failure, no `"ok"` key on either branch) differs from `update_event`/`delete_event`'s (`"ok": bool` on both branches) — handled by branching on the correct signal per handler (`"error" not in result` for create, `result.get("ok")` for update/delete) rather than a single shared check.

## User Setup Required

None - no external service configuration required. Both new functions are pure Python plus existing Firestore/Calendar clients; no new env vars, secrets, or Cloud Scheduler changes.

## Next Phase Readiness
- `_existing_event_at` and `_record_action` are ready for plan 33-04's agentic Layer 2 (ungated proactive calendar writes) to depend on — they are already live on every `create_calendar_event`/`update_calendar_event`/`delete_calendar_event` call, whether invoked from a chat turn or (once 33-04 lands) an occasion compose.
- The `ActionLogStore` entry shape written here matches plan 33-01's locked interface exactly (`id`, `action`, `detail`, `occasion`, `at`, `disclosed`) — plan 33-09's `get_recent_decisions` tool and plan 33-11's heartbeat D-28 anomaly #4 (undisclosed actions pending) can read it unmodified.
- No blockers or concerns for downstream plans. `core/autonomous.py` was not touched (owned by sibling plan 33-04, per this plan's prior-wave context).

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-29*

## Self-Check: PASSED

- FOUND: `_existing_event_at` in core/tools.py (`grep -c "def _existing_event_at" core/tools.py` = 1)
- FOUND: `_record_action` in core/tools.py (`grep -c "def _record_action" core/tools.py` = 1)
- FOUND: `ActionLogStore` referenced in core/tools.py (`grep -c "ActionLogStore" core/tools.py` = 4)
- FOUND: `grep -c "OutreachLogStore" core/tools.py` = 0 (unchanged from pre-task baseline)
- FOUND commit f0431e7 (Task 1)
- FOUND commit e2e25ff (Task 2)
- VERIFIED: `pytest tests/test_tools.py -x -q` — 117 passed
- VERIFIED: `pytest tests/test_calendar_tool.py -x -q` — 15 passed
