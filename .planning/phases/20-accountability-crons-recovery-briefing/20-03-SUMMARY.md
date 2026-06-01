---
phase: 20-accountability-crons-recovery-briefing
plan: 03
subsystem: telegram-infra
tags: [telegram, callback-query, inline-keyboard, router, calendar, tdd]

# Dependency graph
requires:
  - plan: 20-01
    provides: "PendingPromptStore.get_open_note_session for reply-to detection in _check_pending_note_reply"

provides:
  - "send_and_inject accepts reply_markup (InlineKeyboardMarkup) and returns telegram.Message on all paths"
  - "MessageRouter._handle_callback_query: allow-list guarded, spinner-answered, prefix-dispatched (rpe:/watchoff:/skipreason:)"
  - "MessageRouter._check_pending_note_reply: PendingPromptStore lookup by message_id, lazy training_checkin.attach_note"
  - "GoogleCalendarManager.get_calendar_id_by_name: paginated calendarList lookup, never-raises"
  - "GoogleCalendarManager.list_training_events: resolves by name, filters Get Ready:/Travel: buffers, never-raises"
  - "_TRAINING_CALENDAR_NAME = 'Training' module constant (D-01)"

affects:
  - "20-04 (training check-in cron) — builds handle_rpe_callback/handle_watchoff_callback/handle_skipreason_callback/attach_note in core/training_checkin.py"
  - "All cron modules sending inline keyboards — can now use reply_markup kwarg + capture message_id from returned Message"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "callback_query dispatch: branch inserted BEFORE update.message is None guard (Pitfall 2 avoidance)"
    - "Lazy import with ImportError guard: Plan 03 ships independently of Plan 04 (core.training_checkin not required at import time)"
    - "T-20-04 access control: allowed_user_ids check BEFORE any callback dispatch"
    - "T-20-05 input validation: unknown callback_data prefix logged + discarded, not raised"
    - "Reply-to detection: PendingPromptStore.get_open_note_session + message_id match; falls through on False"
    - "Calendar name resolution via calendarList() pagination loop (Pitfall 6: handles multi-page results)"
    - "_TRAINING_CALENDAR_NAME class constant for D-01 configurability"

key-files:
  modified:
    - "core/scheduled_message.py"
    - "interfaces/_router.py"
    - "mcp_tools/calendar_tool.py"
    - "tests/test_scheduled_message.py"
  created:
    - "tests/test_router_callback_query.py"

key-decisions:
  - "Lazy import of core.training_checkin in _handle_callback_query and _check_pending_note_reply so Plan 03 deploys without Plan 04"
  - "send_and_inject return type changed from None to telegram.Message (needed for message_id capture in check-in cron)"
  - "Reply-to detection uses _check_pending_note_reply returning bool — False falls through to normal text handling (not a dead end)"
  - "get_calendar_id_by_name uses full pagination loop to handle accounts with many calendars"
  - "_TRAINING_CALENDAR_NAME as a class-level constant (not a global) to keep it co-located with the methods that use it"

# Metrics
duration: 25min
completed: 2026-06-01
---

# Phase 20 Plan 03: Telegram Infrastructure for Training Check-in Summary

**Inline-keyboard callback_query dispatch + reply-to detection in MessageRouter, send_and_inject reply_markup extension + Message return, and training-calendar read path (get_calendar_id_by_name + list_training_events) in GoogleCalendarManager**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-01T09:11:49Z
- **Completed:** 2026-06-01T09:36:00Z
- **Tasks:** 3 (Tasks 1 and 2 used TDD RED→GREEN; Task 3 direct implementation)
- **Files modified:** 5 (4 modified, 1 created)

## Accomplishments

- `core/scheduled_message.py` extended: `reply_markup=None` keyword-only arg passed through to `bot.send_message`; return type changed from `None` to `telegram.Message` on all code paths (early-return and injection-path both return `msg`); existing callers unaffected (backward-compatible default)
- `interfaces/_router.py` extended with callback_query dispatch: new branch before the `update.message is None` guard dispatches all button taps to `_handle_callback_query`; T-20-04 allow-list check runs before any dispatch; spinner cleared via `cq.answer()` immediately; prefixes `rpe:`, `watchoff:`, `skipreason:` routed to `core.training_checkin` handlers (lazy import + ImportError guard so Plan 03 ships independently of Plan 04); unknown prefix logged + discarded (T-20-05)
- `interfaces/_router.py` extended with reply-to detection: `_check_pending_note_reply` uses `PendingPromptStore.get_open_note_session` + `message_id` match to detect user replies to notes prompts; returns True (handled) or False (fall through); never raises
- `mcp_tools/calendar_tool.py` extended: `_TRAINING_CALENDAR_NAME = "Training"` class constant (D-01); `get_calendar_id_by_name` iterates calendarList with full pagination loop (Pitfall 6), never raises; `list_training_events` resolves calendarId by name (not hardcoded `"primary"`), filters `Get Ready:` and `Travel:` buffer blocks (D-02), never raises
- `tests/test_router_callback_query.py` created: 15 tests covering send_and_inject (reply_markup pass-through, Message return, backward compat) and router (callback not dropped, unauthorised rejected, spinner answered, rpe/watchoff/skipreason dispatch, unknown prefix, ImportError graceful, text path unaffected, reply-to detection with handled=True and handled=False cases)
- `tests/test_scheduled_message.py` updated: 2 existing assertions updated to include `reply_markup=None` in expected call args (Rule 1 auto-fix)

## Task Commits

1. **Task 1: RED — failing send_and_inject + router tests** - `e776329` (test)
2. **Task 1: GREEN — extend send_and_inject** - `e48ba85` (feat)
3. **Task 2: GREEN — router callback_query dispatch** - `8d3aff2` (feat)
4. **Task 3: calendar training-events read path** - `2bc67d5` (feat)

Note: Task 1 and Task 2 share the same RED commit (the test file was written with all router tests upfront) and Task 2 GREEN is commit `8d3aff2`.

## Files Created/Modified

- `tests/test_router_callback_query.py` — 15 tests for send_and_inject reply_markup + router callback_query dispatch + reply-to detection
- `core/scheduled_message.py` — reply_markup kwarg + Message return type (68 lines total, +12 lines changed)
- `interfaces/_router.py` — callback_query dispatch branch + _handle_callback_query + _check_pending_note_reply (+117 lines)
- `mcp_tools/calendar_tool.py` — get_calendar_id_by_name + list_training_events + _TRAINING_CALENDAR_NAME (+110 lines)
- `tests/test_scheduled_message.py` — 2 assertion updates to match new reply_markup=None default

## Decisions Made

- Lazy import + ImportError guard for `core.training_checkin` in both `_handle_callback_query` and `_check_pending_note_reply` — Plan 03 deploys cleanly before Plan 04 exists
- `send_and_inject` return type: `None` → `telegram.Message` — required by Plan 04 check-in cron to capture `message_id` for reply-to detection
- `_check_pending_note_reply` returns `bool` (True = handled, stop; False = fall through) — clean sentinel pattern that preserves normal text handling when reply is not a pending note
- `get_calendar_id_by_name` uses a `while True` pagination loop with `nextPageToken` — necessary for users with more calendars than a single page (Pitfall 6)
- `_TRAINING_CALENDAR_NAME` declared as a class-level constant on `GoogleCalendarManager` — co-located with usage, D-01 configurable without magic strings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed existing scheduled_message tests to match new reply_markup=None default**
- **Found during:** Task 1 GREEN
- **Issue:** `tests/test_scheduled_message.py` tests `test_sends_telegram_message` and `test_no_conversation_inject_by_default` used `assert_called_once_with(chat_id=..., text=...)` without `reply_markup`; the new implementation always passes `reply_markup=None` to `bot.send_message`, causing assertions to fail
- **Fix:** Updated both assertions to include `reply_markup=None` in the expected call args
- **Files modified:** `tests/test_scheduled_message.py`
- **Commit:** `e48ba85` (included in same feat commit as the implementation)

## Known Stubs

None — all three extensions are fully implemented. No placeholder data, hardcoded empty values, or incomplete dispatch paths. The only deferred behavior is `core.training_checkin` handlers (Plan 04), which are correctly handled by lazy import + ImportError guard (not a stub — it's an intentional decoupling).

## Threat Flags

None — all T-20-04/T-20-05/T-20-06/T-20-07 mitigations from the plan's threat register are implemented:
- T-20-04: `allowed_user_ids` check before any callback dispatch (lines 74–79 in `_router.py`)
- T-20-05: prefix allow-list dispatch; unknown prefix logged + discarded
- T-20-06: PendingPromptStore soft-TTL enforced by Plan 01's `get()` method (used in `_check_pending_note_reply`)
- T-20-07: accepted — single-user OAuth, calendarList returns only the user's own calendars

## Self-Check: PASSED
