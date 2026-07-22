---
phase: 32-unified-situation-ambient-memory
plan: 05
subsystem: infra
tags: [firestore, groq, tick-brain, heartbeat, cost-metering, mem-06]

# Dependency graph
requires:
  - phase: 30.5-brain-upgrade
    provides: core/heartbeat.py's check_daily_spend()/CostTripwireLogStore date-keyed
      once/day-suppression pattern, and TICK_BRAIN_FALLBACK_* decoupled Gemini fallback
      client used as the at-cap route
provides:
  - GroqTokenLedgerStore (memory/firestore_db.py) — date-keyed Firestore counter for
    Groq's free-tier 200K tokens/day cap, incremented only on primary tick-brain calls
  - TickBrain.think() at-cap routing — skips the Groq primary and goes straight to the
    existing Gemini fallback once today's ledger total reaches 200K
  - check_groq_budget() heartbeat alert — once/day, fires at 80% of the cap or on a
    tick_fallback/tick_autonomous_fallback call-count spike
affects: [phase-33-occasion-cascade]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Date-keyed Firestore counter store (one doc/day, new date = reset) for
      metering an external free-tier budget with no vendor-provided remaining header"
    - "Once/day alert suppression via an 'alerted_at' field on the same day-doc,
      distinct from CostTripwireLogStore's separate-collection doc-existence check"
    - "D-10 send-then-mark gating: mark_alerted/mark_fired only after send_and_inject
      succeeds, so a delivery failure retries on the next hourly tick"

key-files:
  created:
    - prompts/groq_budget.md
  modified:
    - memory/firestore_db.py
    - core/tick_brain.py
    - core/heartbeat.py
    - tests/test_tick_brain.py
    - tests/test_heartbeat.py

key-decisions:
  - "Dedicated GroqTokenLedgerStore chosen over extending LLMUsageStore (per-purpose
    token fields don't exist there today) — smaller blast radius, no risk of
    double-counting Gemini-billed fallback tokens against the Groq cap"
  - "already_alerted/mark_alerted key off an 'alerted_at' field on the ledger's own
    day-doc (merge=True) rather than a separate suppression collection, since
    increment() already creates the day's doc well before the 80% threshold"
  - "Fallback-purpose spike threshold set to 10 calls/day (mirrors the existing
    _FALLBACK_WARN_THRESHOLD=10 used for the smart-brain Gemini->Haiku degradation
    check) — no numeric threshold was specified in the plan or research doc"
  - "Added prompts/groq_budget.md (new file, outside the plan's declared
    files_modified) — reusing prompts/cost_tripwire.md verbatim would feed a
    dollar-shaped prompt a token/fallback-count payload it cannot correctly narrate"

patterns-established:
  - "GroqTokenLedgerStore.increment() is call-purpose-filtered at the store boundary
    (frozenset check inside increment(), not at the caller) so any future caller
    passing a *_fallback purpose is a silent no-op rather than a caller-side bug risk"

requirements-completed: [MEM-06]

# Metrics
duration: 25min
completed: 2026-07-22
---

# Phase 32 Plan 05: Groq Daily Token Ledger Summary

**Local Firestore counter meters Groq's free-tier 200K tokens/day cap, routes tick-brain to the existing Gemini fallback at the cap, and warns once/day at 80% or on a fallback-call spike.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-22T23:04:00+03:00 (approx, first commit 23:07:48+03:00)
- **Completed:** 2026-07-22T23:15:51+03:00
- **Tasks:** 3 / 3
- **Files modified:** 5 modified, 1 created

## Accomplishments
- `GroqTokenLedgerStore` (date-keyed Firestore counter, sibling to `CostTripwireLogStore`) increments only on primary (Groq-billed) tick-brain purposes, never on `*_fallback` purposes
- `TickBrain.think()` checks the ledger before every primary attempt; at/over 200K tokens it skips Groq entirely and routes straight to the existing decoupled Gemini fallback (D-08) — ticks keep judging, just metered
- `check_groq_budget()` fires a Klaus-composed, once-per-day heartbeat alert at 80% of the cap and/or on a `tick_fallback`/`tick_autonomous_fallback` call-count spike, with a deterministic plain-text fallback and D-10 send-then-mark gating

## Task Commits

Each task was committed atomically:

1. **Task 1: GroqTokenLedgerStore (date-keyed counter)** - `dbde885` (feat)
2. **Task 2: tick_brain increments on primary success + routes to Gemini fallback at cap** - `46820f7` (feat)
3. **Task 3: heartbeat check_groq_budget — 80% + fallback-spike alert, once/day** - `74a36cb` (feat)

## Files Created/Modified
- `memory/firestore_db.py` - `GroqTokenLedgerStore` class (increment/today/already_alerted/mark_alerted)
- `core/tick_brain.py` - `_get_groq_ledger()` helper + `think()` pre-primary cap check and post-primary increment
- `core/heartbeat.py` - `check_groq_budget()`, `_compose_groq_budget_alert()`, `_groq_budget_plain_text_fallback()`, `_send_groq_budget_alert()`, wired into `run_tick()`
- `prompts/groq_budget.md` - new Klaus-voiced compose prompt for the token/fallback-count payload shape
- `tests/test_tick_brain.py` - 12 `TestGroqTokenLedgerStore` tests + 8 `TestTickBrainGroqLedgerWiring` tests (20 total, all matched by `-k ledger`)
- `tests/test_heartbeat.py` - 14 tests covering `check_groq_budget`, compose/fallback, `_send_groq_budget_alert`, and `run_tick` wiring (all matched by `-k groq_budget`)

## Decisions Made
- Dedicated `GroqTokenLedgerStore` over extending `LLMUsageStore` — flagged in the plan's research as a Phase 35 housekeeping candidate (per-purpose token fields could unify the two stores later, but that's a bigger blast radius than this plan needs)
- Fallback-spike threshold (10 calls/day) chosen by mirroring the codebase's existing `_FALLBACK_WARN_THRESHOLD` magnitude for the smart-brain degradation check, since neither the plan nor the research doc specified an exact number
- `already_alerted`/`mark_alerted` suppression keyed off an `alerted_at` field on the ledger's own day-doc rather than a second collection — simpler, and the day-doc already exists by the time 80% is crossed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `prompts/groq_budget.md`**
- **Found during:** Task 3 (heartbeat `check_groq_budget`)
- **Issue:** The plan's `<action>` says to reuse the once/day-suppression + plain-text-fallback compose *pattern* "verbatim," and the plan's declared `files_modified` for this task lists only `core/heartbeat.py`/`tests/test_heartbeat.py`. Reusing `prompts/cost_tripwire.md` literally (not just its pattern) would feed the LLM a payload shape (`total_tokens`, `cap`, `fraction`, `fallback_calls`) that prompt's instructions don't describe (it only knows `total_cost_usd`/`threshold`/`top_drivers`/`cache_hit_rate`) — the composed message would be wrong or nonsensical.
- **Fix:** Added a new, small prompt file (`prompts/groq_budget.md`) mirroring `cost_tripwire.md`'s voice/shape/length constraints but describing the actual Groq-budget payload fields.
- **Files modified:** `prompts/groq_budget.md` (new)
- **Verification:** `test_compose_groq_budget_alert_uses_purpose_groq_budget_tripwire` and `test_compose_groq_budget_alert_falls_back_on_llm_failure` pass; both compose paths verified.
- **Committed in:** `74a36cb` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Necessary for `check_groq_budget()`'s Klaus-composed alert to be correct; no scope creep beyond a single small prompt file needed by the task's own stated behavior.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. No new env var (per plan constraint); no new Cloud Scheduler job; `groq_token_ledger` is a new Firestore collection created implicitly on first write, same as every other date-keyed store in this codebase.

## Next Phase Readiness
- MEM-06 fully satisfied: local ledger + at-cap Gemini routing + once/day 80%/spike heartbeat alert, all verified by `pytest tests/test_tick_brain.py -k ledger -x` (20 passed) and `pytest tests/test_heartbeat.py -k groq_budget -x` (14 passed)
- Full `tests/test_tick_brain.py` (58 passed), `tests/test_heartbeat.py` (60 passed), `tests/test_firestore_db.py` (69 passed), and `tests/test_autonomous.py` (89 passed) all green after this plan — no regressions
- Both plan-specified grep checks pass: `class GroqTokenLedgerStore` in `memory/firestore_db.py`, `def check_groq_budget` in `core/heartbeat.py`
- No blockers for Phase 33 (Occasion Cascade), which depends on MEM-06's ledger being complete before routing nightly/morning traffic through triage (per `.planning/STATE.md`'s v6.0 sequencing constraints)

---
*Phase: 32-unified-situation-ambient-memory*
*Completed: 2026-07-22*
