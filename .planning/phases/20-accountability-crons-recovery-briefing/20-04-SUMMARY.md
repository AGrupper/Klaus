# Plan 20-04 Summary — Training Check-In Engine

**Status:** Complete (3/3 tasks)
**Requirements:** CHECKIN-01, CHECKIN-02, CHECKIN-03, CHECKIN-04, CHECKIN-05, CHECKIN-06

## What was built

`core/training_checkin.py` — the evidence-first training check-in folded into the
21:30 proactive-alerts cron (D-09):

- **`run_training_checkin(bot, today_iso)`** — silent-syncs today's Garmin
  activities to `TrainingLogStore` (`source="garmin"`), scans the Training
  calendar for time-gated unlogged workouts (D-07: future-start events skipped),
  and branches each into an RPE keyboard (Garmin record, no RPE) or a watch-off
  keyboard (no Garmin record) per D-08/D-10. Fully silent when every planned
  workout is already covered (CHECKIN-05) — zero Telegram messages.
- **Keyboards** — exact UI-SPEC callback_data: `rpe:{key}:1..10` (two rows of 5),
  `watchoff:{key}:done|skipped`, `skipreason:{key}:{rest_recovery|sick_injured|too_busy|other}`.
- **D-10 matching** — `_MATCH_BUFFER_MINUTES = 30` + `_ACTIVITY_TYPE_MAP` loose
  type match; `five fingers` → always watch-off (D-03).
- **Four router-dispatched handlers** — `handle_rpe_callback`,
  `handle_watchoff_callback`, `handle_skipreason_callback`, `attach_note` —
  with stale/forged-session rejection (PendingPromptStore.get → None → error
  copy, no write; T-20-08/09) and `PendingPromptStore.delete` on every terminal
  transition (Pitfall 3). Keyboards sent with `inject_into_conversation=False`
  (Pitfall 9); notes-prompt `message_id` stored for reply-to matching.

`core/proactive_alerts.py` — fold-in (D-09): `run_training_checkin(bot, today)`
invoked from `run_proactive_alerts` **before** the `_already_sent` dedup gate so
a same-evening retry is not blocked (Pitfall 5); wrapped non-fatally; reuses the
existing `_TZ` constant; scans TODAY while the alert scan targets tomorrow.

## Tests

`tests/test_training_checkin.py` — 28 tests, all green (silent sync, silent-when-
covered, RPE/watch-off/skip-reason keyboard layouts, time-gating, branch logic,
all four callback handlers, notes step, stale-session rejection). Existing
`tests/test_proactive_alerts.py` (4 tests) unaffected.

## Recovery note

This plan's executor was interrupted by a session-usage limit after writing the
RED test (committed `73ccbb7`) and the full implementation (uncommitted). The
orchestrator closed it out: committed the GREEN implementation (`3f7108d`,
covers Tasks 1+2 — the impl was already complete and all 28 tests passed),
implemented and committed the Task 3 fold-in (`1a602ef`), and wrote this SUMMARY.
No work was redone or lost.

## Key files

- `core/training_checkin.py` — `async def run_training_checkin` (line ~329),
  silent sync (~269), keyboards (~126–158), handlers (~486–700)
- `core/proactive_alerts.py` — fold-in call at line ~105 (before `_already_sent` at ~110)
- `tests/test_training_checkin.py` — 28 tests

## Self-Check: PASSED
