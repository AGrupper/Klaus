---
phase: 31-standing-directives
plan: 05
subsystem: crons
tags: [standing-directives, morning-briefing, weekly-review, fenced-json-trailer, veto]

# Dependency graph
requires:
  - phase: 31-standing-directives (Plan 01)
    provides: StandingDirectiveStore (memory/firestore_db.py) — list_active()
  - phase: 31-standing-directives (Plan 03)
    provides: render_standing_directives_block(directives, *, style) shared formatter
provides:
  - "core/morning_briefing.py: standing-directive gather + _parse_briefing_skip + skipped_by_directive path (run_morning_briefing now returns bool)"
  - "core/weekly_training_review.py: standing-directive gather + _parse_review_skip + skipped_by_directive path"
affects: [31-06, 33-occasion-cascade]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fenced-JSON-trailer skip verdict (```json {\"skip\": true, \"reason\": \"...\"}```), reusing core.autonomous._parse_followup_action's EXACT convention — _parse_briefing_skip and _parse_review_skip both mirror it verbatim"
    - "run_morning_briefing now returns bool (True = vetoed by directive) so handle_tick's post-await state writes don't clobber the skipped_by_directive status with 'sent'"
    - "Directive-skip is the one sanctioned exception to D-24 (weekly review 'always sends') — implemented entirely inside each composer's own LLM call, no new LLM call, no cascade machinery"

key-files:
  created: []
  modified:
    - core/morning_briefing.py
    - prompts/morning_briefing.md
    - core/weekly_training_review.py
    - prompts/weekly_training_review.md
    - tests/test_morning_briefing.py
    - tests/test_weekly_training_review.py

key-decisions:
  - "run_morning_briefing's signature changed from -> None to -> bool (True on directive skip) so handle_tick can avoid overwriting the skipped_by_directive Firestore status with 'sent' immediately after — a Rule 1 fix beyond the plan's literal text, required for T-31-08 (repudiation) to actually hold at the state-doc layer, not just in logs"
  - "Weekly review has no per-run Firestore state doc (unlike morning briefing's morning_briefings/{date}), so its skip is logged via logger.info only — no _set_state equivalent exists to write to"
  - "_parse_review_skip is a local function (not imported from morning_briefing) — plan explicitly offered either option; kept the two crons' skip-parsers independent, matching each module's existing self-contained style"

patterns-established:
  - "Any future legacy-cron veto site (if one is ever added before Phase 33's cascade replaces this machinery) should mirror _parse_briefing_skip/_parse_review_skip's exact fenced-JSON-trailer shape rather than inventing a new sentinel"

requirements-completed: [DIR-03]

# Metrics
duration: ~20min
completed: 2026-07-20
---

# Phase 31 Plan 05: Legacy Cron Directive Veto (Morning Briefing + Weekly Review) Summary

**Standing directives now have real interim veto power over the morning briefing and Sunday weekly review — each composer's own LLM call may emit a fenced-JSON skip verdict instead of a message, logged distinctly as `skipped_by_directive` and never conflated with an infra failure.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-20T08:45 (branch base)
- **Completed:** 2026-07-20T09:02
- **Tasks:** 2 completed
- **Files modified:** 6

## Accomplishments

- `core/morning_briefing.py::_gather_data` best-effort reads `StandingDirectiveStore.list_active()` into `data["standing_directives"]` (fail-open to `[]`)
- `prompts/morning_briefing.md` renders the directives block (via `render_standing_directives_block`) with a D-22 skip-verdict instruction
- `_parse_briefing_skip(text) -> (bool, str, str)` mirrors `core.autonomous._parse_followup_action`'s fenced-JSON-trailer convention exactly
- `run_morning_briefing` now parses the skip verdict right after compose: on skip it logs `skipped_by_directive`, writes a distinct `_set_state` status, and returns **before** `send_and_inject` and **before** the structured/`daily_note` writes — keeping the hub `/api/today` contract intact (T-31-09)
- `run_morning_briefing`'s return type changed `None -> bool`; `handle_tick`'s two post-await `_set_state("sent", ...)` calls now check that bool so they don't immediately clobber the `skipped_by_directive` status (see Deviations)
- `core/weekly_training_review.py::_gather_week_data` reads the same directive list; `prompts/weekly_training_review.md` gets the identical directives block + skip instruction
- `_parse_review_skip` (local, mirrors the same convention) wired into `run_weekly_review` after `_compose_review` — on skip, logs `skipped_by_directive` and returns before `send_and_inject`, the one sanctioned exception to D-24's "always sends" rule
- Module + function docstrings in `weekly_training_review.py` updated to note the directive-skip exception
- 20 new tests across both files (12 in `test_morning_briefing.py`, 10 in `test_weekly_training_review.py` counting the `-k "directive or skip"` filters — see Task Commits), full targeted suites green: `test_morning_briefing.py` 52/52 (+3 pre-existing skips), `test_weekly_training_review.py` 43/43 — no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Morning briefing directive veto (D-21/D-22) + skipped_by_directive** - `1f2b471` (feat)
2. **Task 2: Weekly review directive veto (D-21/D-22)** - `f0ff711` (feat)

## Files Created/Modified

- `core/morning_briefing.py` — `_gather_data` standing-directive read; `_compose_briefing` `{standing_directives}` injection; new `_parse_briefing_skip`; `run_morning_briefing` skip-wiring + `bool` return; `handle_tick`'s two call sites updated to respect the return value
- `prompts/morning_briefing.md` — `{standing_directives}` block + D-22 skip-verdict instruction (fenced JSON) inserted after the coaching guide, before `Today is {today_date}`
- `core/weekly_training_review.py` — `_gather_week_data` standing-directive read (block 9); `_compose_review` `{standing_directives}` injection; new `_parse_review_skip`; `run_weekly_review` skip-wiring; docstrings updated
- `prompts/weekly_training_review.md` — `{standing_directives}` block + skip-verdict instruction inserted after the coaching guide, before `## Your Task`
- `tests/test_morning_briefing.py` — `test_gather_data_reads_standing_directives`, `test_gather_data_standing_directives_fail_open`, `TestParseBriefingSkip` (5 tests), `test_run_morning_briefing_directive_skip_no_send_no_writes`, `test_run_morning_briefing_non_skip_sends_and_writes_structured`
- `tests/test_weekly_training_review.py` — `test_gather_week_reads_standing_directives`, `test_gather_week_standing_directives_fail_open`, `test_compose_review_injects_standing_directives`, `TestParseReviewSkip` (4 tests), `test_run_weekly_review_directive_skip_no_send`, `test_run_weekly_review_non_skip_sends_normally`, `test_weekly_review_prompt_has_standing_directives_and_skip_instruction`

## Decisions Made

- Changed `run_morning_briefing`'s return type from `None` to `bool` (True = vetoed by directive) so `handle_tick` can skip its post-await `_set_state({"status": "sent", ...})` write when the briefing was actually skipped by a directive. Without this, `handle_tick`'s unconditional status write immediately after `await run_morning_briefing(...)` would have overwritten the `skipped_by_directive` Firestore status with `"sent"` on the very next line, defeating T-31-08's repudiation mitigation at the persisted-state layer (the log line alone would have survived, but the Firestore doc — which other consumers might read — would not have). This is a Rule 1 (auto-fix bug) deviation beyond the plan's literal `<action>` text, which only mentioned wiring into `run_morning_briefing` itself; the two `handle_tick` call sites needed the matching update for the fix to actually hold. Both affected `handle_tick` tests are pre-existing `@pytest.mark.skip` (datetime-mocking complexity, documented in the file), so this change carries zero test-breakage risk.
- `_parse_review_skip` is a local function in `weekly_training_review.py` rather than an import from `morning_briefing.py` — the plan explicitly offered either option ("either import a shared helper or add a local `_parse_review_skip`"); kept the two crons independent since neither module currently imports from the other and each already duplicates its own `_compose_*`/prompt-loading logic.
- Weekly review has no per-run Firestore state document analogous to morning briefing's `morning_briefings/{date}` — so the weekly-review skip is logged via `logger.info` only, no `_set_state` equivalent exists to persist to. This satisfies the plan's acceptance criteria verbatim (`grep` for the string + a test asserting `send_and_inject` is not called).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `handle_tick` would have immediately overwritten `skipped_by_directive` with `"sent"`**
- **Found during:** Task 1, while wiring the skip verdict into `run_morning_briefing`
- **Issue:** `handle_tick`'s two call sites (`fast-path` and `sync_detected` branches) call `_set_state(today_iso, {"status": "sent", ...})` unconditionally immediately after `await run_morning_briefing(...)` returns without raising. Since a directive-skip returns normally (not an exception), the "sent" write would land right after `run_morning_briefing`'s own `"skipped_by_directive"` write, silently erasing it — defeating T-31-08 (repudiation: skip must be distinguishable from a crashed cron) at the persisted-state layer.
- **Fix:** `run_morning_briefing` now returns `bool` (`True` = vetoed by directive). Both `handle_tick` call sites now guard their `"sent"` `_set_state` write with `if not skipped_by_directive:`.
- **Files modified:** `core/morning_briefing.py`
- **Commit:** `1f2b471`

## Issues Encountered

**Test-file edit collision:** while appending new tests to the end of `tests/test_weekly_training_review.py`, an `Edit` call's `old_string` boundary was one line short of the true end of file (an off-by-one against `wc -l`'s count, which included a final content line I hadn't read), which briefly orphaned the last assertion of a pre-existing test (`test_compose_review_passes_32k_max_tokens`) at the very end of the file. Caught immediately by running the targeted test suite (`NameError: name 'captured' is not defined`), fixed by moving the orphaned `assert captured.get("max_tokens") == 32000` back into its owning test function before the new Phase-31 test section, then re-ran the full suite green. No functional code was affected — test-file-only mishap, corrected before any commit.

## User Setup Required

None — no external service configuration required. Both crons read through the existing `StandingDirectiveStore` (Plan 01) against the already-provisioned `standing_directives` Firestore collection, and both consume the existing `render_standing_directives_block` shared formatter (Plan 03).

## Next Phase Readiness

The interim-cron site of DIR-03 is now fully live for the two legacy proactive crons safe to silence. Plan 06 (nightly review) is exempt by design — it is the veto/announcement channel itself and is handled separately. Phase 33's unified occasion cascade will eventually replace this per-cron veto machinery with a single upstream gate; until then, `_parse_briefing_skip`/`_parse_review_skip` establish the exact fenced-JSON-trailer pattern any future interim veto site should reuse verbatim. No blockers for downstream plans.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-20*
