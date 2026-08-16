---
phase: 33-occasion-cascade
plan: 07
subsystem: autonomous-engine
tags: [morning-briefing, cascade, occasion, push-trigger, firestore, telegram]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-04 core.autonomous.run_occasion_cascade / _run_cascade — the shared 3-layer cascade this plan routes the morning briefing through; 33-05 core.tools._existing_event_at / _record_action (read for context, not directly consumed here)"
provides:
  - "core/morning_briefing.py::run_morning_briefing_triggered — the push-triggered, cascade-only morning briefing entry point plan 33-10's /internal/process-occasion calls by this exact name/signature"
  - "D-05/D-06 write-timing inversion — structured snapshot + daily_note written unconditionally (sent or skipped), sourced from final_text on a send or the Layer-1 draft on a skip"
  - "D-15 widened window (_gather_data['nightly_ran'] / ['yesterday']) — a night without a nightly wind-down doesn't drop out of the morning's narrative"
  - "D-20 Sunday deferral signal (_gather_data['weekly_review_due_today']) — consumed by prompts/morning_occasion.md (33-03) to stay light on training"
  - "core/tools.py::_handle_run_morning_briefing repointed at run_morning_briefing_triggered(trigger='manual', dedup=False) — D-14"
affects: [33-10, 33-11, 33-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SC-1 caller-side plain-text fallback: a top-level try/except around run_occasion_cascade() itself (not just the cascade's own internal try/excepts) sends the deterministic _plain_text_fallback() directly and records composed_via='plain_text_fallback' — the interfaces block's documented third composed_via value, otherwise unreachable since _run_cascade only ever sets 'llm'/'draft_fallback'."
    - "D-18 shared-namespace read for a same-day cross-occasion signal: D-20's weekly_review_due_today is detected via OutreachLogStore.topics_today(today_iso) (checking for a 'weekly:' prefix) rather than a new state doc — reuses the exact namespace occasions already share for repeat-suppression, with no new store."

key-files:
  created: []
  modified:
    - core/morning_briefing.py
    - core/tools.py
    - tests/test_morning_briefing.py

key-decisions:
  - "On a genuine infra failure (Layer-1 exception, send failure) with no judgment skip, the function still writes status='skipped_by_judgment' via the same skip branch — the plan's <action> text only defines two branches (send / judgment skip) and the <interfaces> status enum lists exactly four values with no fifth 'error' status, so a bare decision['sent'] is False routes to the skip branch regardless of why. A raised exception from run_occasion_cascade itself is handled separately via the SC-1 plain-text fallback (see next decision), which is the one infra-failure case the interfaces block explicitly anticipates (composed_via='plain_text_fallback')."
  - "Added a top-level try/except around the run_occasion_cascade() call with an SC-1 plain-text-fallback send, even though Task 1's <action> text doesn't spell this out step-by-step — the <interfaces> block (authoritative per the plan's own framing: 'Contract this plan CREATES') documents composed_via can be 'plain_text_fallback', a value _run_cascade itself never produces (verified: only 'llm'/'draft_fallback'). Without this, that documented value would be permanently unreachable and a catastrophic gather_situation() failure (uncaught inside run_occasion_cascade) would leave the morning silent with no backstop (D-09) — Rule 2 (missing critical functionality)."
  - "daily_note on a judgment skip uses decision['draft'] verbatim (no first-line extraction) per the plan's literal wording ('decision[\"draft\"]', vs. the send branch's explicit 'first non-empty line of decision[\"final_text\"]') — Layer 1's draft is itself already a one-liner by convention, so this is not a behavioral gap in practice, just literal fidelity to two differently-worded plan clauses."
  - "D-20's 'weekly has not yet sent for today' check reads OutreachLogStore.topics_today(today_iso) for a 'weekly:' prefix rather than depending on a weekly_reviews state doc — sibling plan 33-08 (not in this plan's base commit) may add one, but D-18's shared OutreachLogStore namespace already carries this exact signal today with no cross-plan dependency."
  - "The daily_note SelfStateStore.set() write is now truly unconditional (no `if daily_note:` guard, unlike the legacy run_morning_briefing) — matches the plan's explicit 'unconditionally' wording for D-06; an empty draft on a degenerate skip still writes an empty daily_note rather than leaving a stale prior note in place."

patterns-established: []

requirements-completed: [OCC-02]

# Metrics
duration: ~45min
completed: 2026-07-29
---

# Phase 33 Plan 07: Push-Triggered Morning Briefing Cascade Summary

**`run_morning_briefing_triggered` replaces the Garmin-poll/10:15-cutoff state machine with an immediate, cascade-only entry point (D-08/D-09/D-30) that names a missing sleep sync instead of gating on it, writes the Hub's daily snapshot independently of whether Klaus spoke (D-05/D-06), widens its window when last night's nightly never ran (D-15), and defers training to the Sunday weekly (D-20) — while the legacy `handle_tick`/`run_morning_briefing` cron path survives completely untouched for the D-31 dark-ship window.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-07-29 (session start, post worktree base-correction)
- **Completed:** 2026-07-29T23:13:43+03:00 (final task commit)
- **Tasks:** 2/2
- **Files modified:** 3 (`core/morning_briefing.py`, `core/tools.py`, `tests/test_morning_briefing.py`)

## Accomplishments

- **`run_morning_briefing_triggered(bot, today_iso, *, trigger, dedup=True) -> bool`** — the exact interface signature the plan's `<interfaces>` block locks for plan 33-10's `/internal/process-occasion` to call. No hour check, no `_fetch_garmin_safe` precondition, no time floor: the function proceeds unconditionally once triggered (D-09). D-12 dedup treats `{"sent", "manual", "skipped_by_judgment", "skipped_by_directive"}` as terminal — a snooze, second alarm, or Sleep Focus toggled off/on/off is a pure no-op before any LLM call.
- **D-11 gap-naming**: when `_gather_data`'s existing `garmin={"state": 2}` fallback fires (no sync yet), `today_data["garmin_missing"] = True` is set explicitly before the data reaches the cascade, so the compose layer cannot silently drop the gap.
- **D-30 — no feature-flag branch**: unlike nightly/weekly's A/B rollout, morning routes through `core.autonomous.run_occasion_cascade` unconditionally; verified via `grep -c "OCCASION_CASCADE" core/morning_briefing.py` == 0 (including in comments/docstrings, per the plan's literal grep gate).
- **SC-1 plain-text fallback**: a top-level `try/except` around the `run_occasion_cascade` call itself (distinct from the cascade's own internal error handling) sends `_plain_text_fallback()` directly and records `composed_via="plain_text_fallback"` on any catastrophic exception (e.g. a raising `gather_situation()`) — the one `composed_via` value the `<interfaces>` block documents that `_run_cascade` itself can never produce. See Deviations.
- **D-05/D-06 write-timing inversion**: the `structured` snapshot and `daily_note`/`daily_note_date` are now written **unconditionally** — sent, judgment-skipped, or via the SC-1 fallback. `daily_note` sources the first non-empty line of `decision["final_text"]` on a send (identical to the legacy one-liner logic) or `decision["draft"]` verbatim on a skip (Layer 1's own free one-liner — the thing Klaus judged wasn't worth interrupting Amit over). `CoachingTopicStore.add_topic` stays strictly send-gated (T-24-17 write-after-send discipline unchanged).
- **D-15 widened window**: `_gather_data` now derives `data["nightly_ran"]` from `core.nightly_review._get_state(yesterday_iso)`'s status (`"sent"` or `"skipped_by_judgment"` = terminal, matching 33-06's forward-compatible status set even though that plan isn't in this plan's base). When the nightly never ran, `data["yesterday"]` is populated with yesterday's calendar + tasks via the existing `_get_calendar_tool()`/`TaskStore` helpers — no new fetch logic.
- **D-20 Sunday deferral**: `data["weekly_review_due_today"]` is set on Sundays (`isoweekday() == 7`) when no `"weekly:"`-prefixed topic key has landed in today's `OutreachLogStore` yet — reusing D-18's shared namespace rather than a new state doc. `prompts/morning_occasion.md` (33-03) already carries the instruction to stay light on training when this flag is set.
- **D-14 manual repoint**: `core/tools.py::_handle_run_morning_briefing` now schedules `run_morning_briefing_triggered(_application.bot, today_iso, trigger="manual", dedup=False)` instead of the legacy `run_morning_briefing` — the existing `"manual"` state marker and Telegram-facing response string are unchanged.
- **Legacy path untouched**: `handle_tick`, `run_morning_briefing`, `_compose_briefing`, `_parse_briefing_skip` are byte-identical to before this plan — verified via `grep -c "async def handle_tick"` == 1 and all pre-existing `handle_tick`/`run_morning_briefing` tests passing unmodified.

## Task Commits

Each task was committed as coherent, fully-tested file-scoped commits rather than two strictly task-isolated diffs — Task 2's D-05/D-06/D-15/D-20 additions live inside the SAME function/`_gather_data` body Task 1 creates, so splitting further would have meant reconstructing an intermediate broken state (same rationale as plan 33-04's precedent):

1. **Tasks 1+2 combined — `core/morning_briefing.py`** - `d22e768` (feat) - `run_morning_briefing_triggered`, D-05/D-06 write-timing inversion, D-15 widened window, D-20 Sunday deferral
2. **Task 1 — `core/tools.py`** - `4c7afe6` (feat) - D-14 manual "brief me" repoint
3. **Tasks 1+2 tests — `tests/test_morning_briefing.py`** - `f52b9d8` (test) - 33 new tests across both tasks

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `core/morning_briefing.py` - New `run_morning_briefing_triggered` (with the SC-1 plain-text fallback and `_TERMINAL_STATUSES` constant) inserted between `run_morning_briefing` and the data-gathering section; `_gather_data`'s existing "since_last_night" block extended with D-15's `nightly_ran`/`yesterday` widening and a new D-20 `weekly_review_due_today` block. `handle_tick`/`run_morning_briefing`/`_compose_briefing`/`_parse_briefing_skip`/`_plain_text_fallback` all unchanged (the last is now also called from the new function's SC-1 path).
- `core/tools.py` - `_handle_run_morning_briefing` repointed at `run_morning_briefing_triggered(..., trigger="manual", dedup=False)`; docstring updated.
- `tests/test_morning_briefing.py` - `TestTriggerMorningEntryPoint` (no time floor, garmin_missing on/off, D-12 dedup over all four terminal statuses parametrized, D-14 dedup=False, SC-1 fallback), `TestHandleRunMorningBriefingRepoint` (tools.py repoint), `TestWriteTimingInversion` (skip/send daily_note sourcing, CoachingTopicStore send-gating, an unconditional-write regression grep), `TestWidenedWindowD15`, `TestSundayDeferralD20`.

## Decisions Made

See `key-decisions` in the frontmatter — summarized: (1) infra failures without an explicit judgment-skip verdict still write `status="skipped_by_judgment"` since the plan/interfaces define only two branches; (2) an SC-1 top-level fallback was added beyond the task's literal step list because the `<interfaces>` block's `composed_via` enum requires it to be reachable; (3) `daily_note` on a skip uses `decision["draft"]` verbatim per the plan's differently-worded send-vs-skip clauses; (4) D-20 detection reuses the existing `OutreachLogStore` namespace instead of depending on sibling plan 33-08's not-yet-existent state doc; (5) the `daily_note` SelfStateStore write dropped its legacy `if daily_note:` truthiness guard to honor "unconditionally" literally.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Added the SC-1 plain-text fallback around `run_occasion_cascade`**
- **Found during:** Task 1, while cross-checking the `<interfaces>` block's `composed_via` enum against `_run_cascade`'s actual code in `core/autonomous.py`
- **Issue:** The plan's `<interfaces>` block documents `composed_via: "llm" | "draft_fallback" | "plain_text_fallback"`, but `core.autonomous._run_cascade` only ever sets `"llm"` or `"draft_fallback"` (verified by reading the full function body) — `"plain_text_fallback"` is unreachable unless the *caller* (this function) produces it. Without a caller-side fallback, an uncaught exception from `run_occasion_cascade` itself (e.g. a raising `gather_situation()`, which is not wrapped in the cascade's own internal try/excepts) would propagate out of `run_morning_briefing_triggered` entirely, leaving the morning silent with no backstop per D-09.
- **Fix:** Wrapped the `run_occasion_cascade` call in its own top-level `try/except`; on any exception, compose `_plain_text_fallback(today_data, today_iso)` and send it directly via `send_and_inject`, recording `composed_via="plain_text_fallback"` in the subsequent `status="sent"` state write. A further send failure inside the fallback itself is caught and logged — never re-raised.
- **Files modified:** `core/morning_briefing.py`
- **Verification:** `TestTriggerMorningEntryPoint::test_sc1_cascade_raises_falls_back_to_plain_text_send` — asserts the fallback sends and records `composed_via="plain_text_fallback"`.
- **Commit:** `d22e768`

### Test-Environment-Only Adjustment (not a code deviation)

**`_handle_run_morning_briefing`'s existing `asyncio.get_event_loop()` call needed an explicit event loop in its new test.** This is pre-existing production code (unchanged by this plan beyond the function-name repoint) that relies on `asyncio.get_event_loop()` returning the currently-running loop — true in production, where this handler always executes inside a live async request context (Cloud Tasks dispatch / `/internal/process-update`). In this test file, an earlier test's `asyncio.run()` explicitly clears the thread's set event loop on exit (Python 3.13 `asyncio.Runner` behavior), so a later synchronous call to `asyncio.get_event_loop()` with no running loop raises `RuntimeError`. Fixed by giving the new test its own `asyncio.new_event_loop()`/`set_event_loop()` pair (closed in a `finally`) — test-environment setup only, no production code touched.

## Issues Encountered

None beyond the two items above (both resolved). No auth gates, no checkpoints.

## User Setup Required

None — no external service configuration, no new env vars, no Cloud Scheduler/Secret Manager changes. `MORNING_TRIGGER_TOKEN`, `POST /trigger/morning`, and the Cloud Tasks dispatch wiring are plan 33-10's responsibility, not this plan's.

## Next Phase Readiness

- `run_morning_briefing_triggered(bot, today_iso, *, trigger, dedup=True) -> bool` is ready for plan 33-10's `/internal/process-occasion` to call by this exact name and signature, per the plan's own `<interfaces>` contract.
- The `morning_briefings/{date}` document now carries `status`, `composed_via` (including the previously-unreachable `"plain_text_fallback"` value), `skip_cause`, `trigger`, `sent_at`/`judged_at`, and `structured` exactly as documented in `<interfaces>`.
- `handle_tick`/`run_morning_briefing`/`_compose_briefing`/`_parse_briefing_skip` are untouched and still fully covered by their existing tests — ready for plan 33-12 to delete after the D-31 human-confirmation checkpoint (Amit's Sleep-Focus-off Shortcut confirmed firing).
- D-20's `weekly_review_due_today` flag is read by `prompts/morning_occasion.md` (already shipped in 33-03) — no further prompt work needed from this plan.
- No blockers or concerns for downstream plans. `interfaces/web_server.py` and `core/nightly_review.py`/`core/weekly_training_review.py` were not touched (owned by sibling plans 33-06/33-08/33-10, per this plan's prior-wave context).

## Self-Check: PASSED

- FOUND: `core/morning_briefing.py` (`grep -c "async def run_morning_briefing_triggered"` = 1)
- FOUND: `core/morning_briefing.py` (`grep -c "async def handle_tick"` = 1, unchanged)
- FOUND: `core/morning_briefing.py` (`grep -c "OCCASION_CASCADE"` = 0)
- FOUND: `core/tools.py` repoint (`run_morning_briefing_triggered` referenced in `_handle_run_morning_briefing`)
- FOUND commit `d22e768` (Task 1+2, `core/morning_briefing.py`)
- FOUND commit `4c7afe6` (Task 1, `core/tools.py`)
- FOUND commit `f52b9d8` (tests)
- VERIFIED: `pytest tests/test_morning_briefing.py -x -q` — 76 passed, 3 skipped
- VERIFIED: `pytest tests/test_api_today.py -x -q` — 7 passed
- VERIFIED: `pytest tests/test_tools.py -x -q` — 117 passed

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-29*
