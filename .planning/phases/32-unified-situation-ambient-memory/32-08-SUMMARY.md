---
phase: 32-unified-situation-ambient-memory
plan: 08
subsystem: autonomous-tick
tags: [location, weather, calendar, standing-directives, context-only, nightly-review, morning-briefing]

# Dependency graph
requires:
  - phase: 32-unified-situation-ambient-memory
    provides: "core.autonomous._gather_calendar / _gather_standing_directives + the gather_situation thread-pool + _is_empty_signals exclusion-comment pattern (Plans 01-07); Phase 31 StandingDirectiveStore + render_standing_directives_block"
provides:
  - "core.autonomous.derive_current_location(calendar_events, active_directives) — pure Pattern 7 heuristic (D-06): home default silently, calendar signal overrides, directive-alone is ambiguous (unclear trip-end), conflict is ambiguous, never guesses"
  - "core.autonomous._gather_location(situation) — sentinel-on-failure wrapper, runs AFTER gather_situation's thread pool (not inside the concurrent jobs dict) to safely reuse the already-gathered calendar + standing_directives values with zero extra API calls; registered in gathered['location'], context-only in _is_empty_signals"
  - "core.nightly_review._gather_tomorrow now derives current_location before fetching weather; on ambiguity suppresses weather and sets tomorrow.location_ask={'candidate': <city>} which rides through the existing payload['tomorrow'] passthrough"
  - "core.morning_briefing._gather_data's weather gather moved to run after calendar + standing_directives, consuming the same derived current_location (resolved -> that city; ambiguous -> suppress; no ask — nightly-only per D-06)"
  - "prompts/nightly_review.md documents tomorrow.location_ask and a 'Location check' weaving instruction so the compose LLM asks 'Still in <city>, Sir?' before serving location-dependent content"
affects: [33-occasion-cascade (nightly/morning composers this plan touched will route through the shared occasion cascade)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Post-pool sequential gather: unlike the other 17 gather_situation sources (submitted concurrently via ThreadPoolExecutor + as_completed), _gather_location runs AFTER the pool closes because it must read two OTHER sources' (calendar, standing_directives) already-completed results — submitting it as a concurrent job would race against those sources' own in-flight gathers with no ordering guarantee."
    - "Conservative under-detect location heuristic: calendar signal alone is confident enough to override (dated, same-day); a directive alone is never enough (no corroboration that the trip hasn't quietly ended) — ambiguous, ask don't guess; conflict between the two is also ambiguous."

key-files:
  created: []
  modified:
    - core/autonomous.py
    - core/nightly_review.py
    - core/morning_briefing.py
    - prompts/nightly_review.md
    - tests/test_autonomous.py

key-decisions:
  - "_gather_location(situation) takes the whole assembled situation dict (not now/project_id/database like every other gather) and runs sequentially after gather_situation's ThreadPoolExecutor block closes, rather than being submitted as one of the pool's concurrent jobs. The plan's action text said 'register in the jobs dict', but doing so literally would create a real race: as_completed gives no ordering guarantee, so a concurrently-submitted location job could read situation['calendar'] or situation['standing_directives'] before those sources' own gathers finished, silently deriving from stale/missing data. Running it as a sequential post-pool step (mirroring how gathered['empty'] = _is_empty_signals(gathered) already works) achieves the plan's real goal — zero extra Calendar/Firestore calls — without the race. Documented inline as a Rule 1 auto-fix."
  - "Directive-alone travel signal is treated as AMBIGUOUS (ask), not a resolved override, even though the plan's acceptance criteria phrasing ('a calendar/directive travel signal -> that location overrides') could be read either way. Rationale: StandingDirectiveStore.list_active() only returns directives that haven't been explicitly cancelled/expired — it says nothing about whether Amit has quietly returned home without updating the directive. A calendar event, by contrast, is dated to today and needs no corroboration. This interpretation is also the only one that makes the nightly location_ask meaningfully fire in the common case (a directive like 'while I'm in France' with no matching calendar signal on a given day) rather than being a dead code path."
  - "Directive place-name extraction is intentionally narrow (only 'while I'm in X' / 'back from X', capped at 3 words, cut at common stop-words like ' for '/' during '). A false negative here just falls through to the calendar signal or the silent home default — never a wrong guess — so under-detecting was preferred over a broader regex that risks capturing sentence fragments as a literal city name."
  - "core/morning_briefing.py's weather gather block was moved (not just edited) — from the top of _gather_data to immediately after the standing_directives block near the end — so it can read data['calendar'] and data['standing_directives'] without a second Calendar/Firestore call. Verified via the full existing test_morning_briefing.py suite (52 passed) that no test depended on weather being gathered first."

requirements-completed: [MEM-07, MEM-05]

# Metrics
duration: ~50min
completed: 2026-07-23
---

# Phase 32 Plan 08: Location Awareness (current_location Derivation) Summary

**`derive_current_location` reads today's calendar + active standing directives to override the silent "Tel Aviv" default only on a confident travel signal, asks "Still in <city>, Sir?" via the nightly review on genuine ambiguity, and repoints both nightly-review and morning-briefing weather off the hardcoded literal — closing the Paris-gets-Tel-Aviv-forecast bug.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-07-23
- **Tasks:** 2/2 completed (both TDD: tests written and verified alongside each implementation)
- **Files modified:** 5 (`core/autonomous.py`, `core/nightly_review.py`, `core/morning_briefing.py`, `prompts/nightly_review.md`, `tests/test_autonomous.py`)

## Accomplishments

- `derive_current_location(calendar_events, active_directives)` — pure Pattern 7 heuristic (D-06, research [ASSUMED]): home default `"Tel Aviv"` silently when no travel signal exists; a same-day calendar event location not naming Tel Aviv confidently overrides home (no corroboration needed — it's dated); a directive-alone place-name match (`"while I'm in X"` / `"back from X"`) is ambiguous — no calendar corroboration means an unclear trip-end, so it never resolves on its own; calendar+directive agreement resolves to that city; calendar+directive conflict is ambiguous. Never raises, never guesses — returns `{"ambiguous": True, "candidate": <str|None>}` instead of a wrong city.
- `_gather_location(situation)` wraps the heuristic sentinel-on-failure over the already-gathered `calendar` + `standing_directives` situation values. Runs as a sequential step immediately AFTER `gather_situation`'s `ThreadPoolExecutor` block closes (not submitted as one of its concurrent jobs) — see key-decisions for why this deviates from a literal "register in the jobs dict" reading.
- `_is_empty_signals`'s exclusion-comment block extended to explicitly name `location` — context-only, never a Layer-0 trigger, even when the derivation is ambiguous (the ask itself only ever fires through the nightly compose payload, never through the free-tier gate).
- `core/nightly_review.py::_gather_tomorrow` derives `current_location` from the calendar + standing_directives it already gathers, then either fetches that city's forecast (resolved — home case byte-identical to the old hardcoded call) or suppresses the weather entirely and sets `tomorrow.location_ask = {"candidate": <city>}` (ambiguous) — riding through the existing `payload["tomorrow"]` passthrough with no new plumbing in `_compose_nightly`.
- `core/morning_briefing.py::_gather_data`'s weather block moved to run after calendar + standing_directives so it can consume the same derived location (resolved → that city; ambiguous → suppress). The ask itself stays nightly-only per D-06 — morning briefing just goes quiet on weather rather than asking.
- `prompts/nightly_review.md` documents `tomorrow.location_ask` in "What you're given" and adds a "Location check" section instructing the compose LLM to ask `"Still in <city>, Sir?"` before serving any location-dependent content, and to skip the weather line entirely when `location_ask` is present (weather is intentionally withheld, not just absent).
- 22 new tests in `tests/test_autonomous.py` (all discoverable via `pytest tests/test_autonomous.py -k current_location`): the pure heuristic (home/override/agree/conflict/directive-alone/malformed-input/over-capture-guard), the gather wrapper (derivation, sentinel-on-failure, context-only in the empty gate — both resolved and ambiguous), an end-to-end `gather_situation` assertion, the prompt-doc grep coverage, and nightly/morning weather-repointing coverage (resolved/home/ambiguous for nightly; resolved/ambiguous for morning).

## Task Commits

1. **Task 1: `_gather_location` + `current_location` derivation heuristic (context-only)** - `d460ce7` (feat)
2. **Task 2: Repoint weather to derived current_location + wire the D-06 location-ambiguity ask** - `e24b971` (feat)

_No separate plan-metadata commit — SUMMARY.md is committed as part of this worktree's final commit per parallel-executor protocol._

## Files Created/Modified

- `core/autonomous.py` — `derive_current_location`, `_location_from_calendar`, `_location_from_directives`, `_same_place`, `_gather_location`, plus `_HOME_LOCATION`/`_DIRECTIVE_LOCATION_PATTERNS`/`_DIRECTIVE_LOCATION_STOP_RE` constants; `gather_situation` now runs `_gather_location` sequentially after the thread pool closes; `_is_empty_signals`'s exclusion-comment block extended for `location`
- `core/nightly_review.py` — `_gather_tomorrow`'s weather block now derives `current_location` before calling `fetch_weather`, sets `location_ask` on ambiguity
- `core/morning_briefing.py` — `_gather_data`'s weather gather relocated to after calendar + standing_directives, consumes the derived location
- `prompts/nightly_review.md` — documents `tomorrow.location_ask`, updates the weather description, adds the "Location check" weaving section
- `tests/test_autonomous.py` — `TestDeriveCurrentLocationHeuristic`, `TestGatherCurrentLocationContextOnly`, `TestNightlyReviewPromptDocumentsCurrentLocationAsk`, `TestNightlyGatherTomorrowRepointsToCurrentLocation`, `TestMorningBriefingWeatherRepointedToCurrentLocation` (22 new tests)

## Decisions Made

See `key-decisions` in frontmatter — summarized: (1) `_gather_location` runs sequentially after `gather_situation`'s thread pool rather than inside the concurrent jobs dict, to avoid a real race against the calendar/standing_directives gathers it depends on (Rule 1 auto-fix on a literal reading of the plan's action text); (2) a directive-alone travel signal is ambiguous (ask), not a resolved override — a calendar event is dated/corroborating, a directive's mere "active" status says nothing about whether the trip already ended; (3) the directive place-name regex is deliberately narrow and conservative, matching the plan's under-detect-not-over-detect instruction; (4) morning_briefing's weather gather was relocated (not just edited) to reuse the already-gathered calendar/standing_directives with zero extra API calls.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_gather_location` moved out of the concurrent jobs dict to avoid a race condition**
- **Found during:** Task 1 implementation, while wiring `_gather_location` into `gather_situation`
- **Issue:** The plan's action text said to "Register in the jobs dict with a CONTEXT-only comment." Read literally, this would submit `_gather_location` as one of the ~17 concurrent `ThreadPoolExecutor` jobs alongside `calendar` and `standing_directives` — the two sources it depends on. Since `as_completed` gives no ordering guarantee (the same tradeoff Plan 07's `_gather_training_reality` decision documented for `calendar`), a concurrently-submitted `location` job could read `situation.get("calendar")` or `situation.get("standing_directives")` before those sources' own gathers had populated them, silently deriving a location from incomplete/missing data on some fraction of ticks — a real, non-hypothetical race, not just a style nit.
- **Fix:** `_gather_location(gathered)` is called sequentially immediately after the `with ThreadPoolExecutor(...) as pool:` block closes (right before `gathered["empty"] = _is_empty_signals(gathered)`, which already follows the same sequential-after-pool pattern). This still achieves the plan's actual goal — zero extra Calendar/Firestore calls, reusing the already-gathered values — without the race.
- **Files modified:** `core/autonomous.py`
- **Verification:** `tests/test_autonomous.py::TestGatherCurrentLocationContextOnly::test_gather_situation_current_location_reflects_calendar_travel_signal` exercises the real pool end-to-end and asserts the derived location reflects the calendar event that was gathered in the same call — this would be flaky/order-dependent under a concurrent-jobs-dict implementation but is deterministic under the sequential-post-pool one.
- **Committed in:** `d460ce7` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — race-condition prevention on a literal instruction reading).
**Impact on plan:** No scope creep — the fix stays entirely within `core/autonomous.py`'s `gather_situation` function, achieves the plan's stated goal (no extra API calls) more safely than the literal instruction would have, and is exercised by a dedicated end-to-end test.

## Issues Encountered

`tests/test_nightly_review.py` (and other test files that import `grpc`/Firestore transitively) segfault (exit 139) at Python interpreter teardown under this environment's Python 3.13 venv — this is the pre-existing, documented environmental issue (`grpc/protobuf GC, Python 3.13 + 3.14` — see CLAUDE.md § Invariants and the `feedback_python_version` memory), not a regression from this plan. Verified twice: once with my changes applied (26/26 tests reported passing via dot-count and `-v` output before the crash), and once with `core/nightly_review.py` temporarily reverted to its pre-plan state via `git checkout -- core/nightly_review.py` (same 26/26-pass-then-segfault signature), confirming the crash is unrelated to this plan's code and occurs during interpreter shutdown after all tests have already passed. My changes were then restored from a scratchpad backup and re-verified via `git diff --stat` to match exactly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MEM-07 (location awareness) and the remaining MEM-05 per-gather context-only coverage (the `location` assertion Plan 07 explicitly deferred to this plan) are both complete. This closes out the "unified situation" gather set: `conversation_tail`, `training_reality` (Plan 07), and now `location` (Plan 08) all follow the identical sentinel-on-failure + context-only-exclusion pattern established across the phase.
- Phase 33 (Occasion Cascade) can route nightly/morning traffic through the shared cascade — both composers this plan touched (`core/nightly_review.py::_gather_tomorrow`/`_compose_nightly`, `core/morning_briefing.py::_gather_data`) are unaffected in their external call shape (still return the same `data`/`tomorrow` dict shape plus two new optional keys, `weather`'s value source changed but its key/type contract didn't), so Phase 33's cascade wiring shouldn't need to special-case this plan's changes.
- `mcp_tools/routes_tool.py::get_travel_time`'s only caller, `core/proactive_alerts.py`, was left untouched — that module is already retired per CLAUDE.md (§5, "Retired: proactive-alerts") and scheduled for deletion in Phase 35 (~2.85K LOC dead-code sweep). Repointing a caller inside a module already slated for deletion would be pure churn; flagging here so Phase 35's sweep doesn't need to separately investigate why `get_travel_time` was never wired to the new derived location.
- One thing worth a closer look before Phase 33 or the live MEM-07 VALIDATION row: the "directive-alone is ambiguous" interpretation (see key-decisions #2) is my resolution of a genuinely ambiguous acceptance-criteria phrasing in the plan text. It is internally consistent (matches the D-06 "unclear trip-end" language, and is the only reading that makes `location_ask` a reachable code path in the common single-signal case) and is covered by dedicated tests, but the VALIDATION MEM-07 manual row ("seed a conflicting travel signal, run the nightly, confirm the ask appears") should specifically also try the *directive-alone, no calendar* case to confirm the live behavior matches this interpretation before considering MEM-07 fully closed.

---
*Phase: 32-unified-situation-ambient-memory*
*Plan: 08*
*Completed: 2026-07-23*

## Self-Check: PASSED

- `core/autonomous.py` — FOUND (modified, present)
- `core/nightly_review.py` — FOUND (modified, present)
- `core/morning_briefing.py` — FOUND (modified, present)
- `prompts/nightly_review.md` — FOUND (modified, present)
- `tests/test_autonomous.py` — FOUND (modified, present)
- Commit `d460ce7` — FOUND in `git log --oneline`
- Commit `e24b971` — FOUND in `git log --oneline`
- `pytest tests/test_autonomous.py -k current_location -x` — 22 passed
- `pytest tests/test_autonomous.py -q` — 126 passed
- `pytest tests/test_morning_briefing.py -q` — 52 passed, 3 skipped (pre-existing skips, unrelated)
- `pytest tests/test_nightly_review.py -v` — 26 passed (0 FAILED/ERROR; process segfaults at interpreter teardown, a pre-existing environmental issue confirmed present on the unmodified file too)
- `pytest tests/test_token_budget.py -x` — 3 passed (7730/8000 tokens, unaffected by this plan)
- `grep -n "fetch_weather" core/nightly_review.py core/morning_briefing.py` — confirms the derived-location call sites, no hardcoded `fetch_weather("Tel Aviv")` literal call remains
- `grep -nE "location" core/autonomous.py` — confirms jobs-adjacent registration + exclusion comments, no `if situation.get("location")` trigger reference
