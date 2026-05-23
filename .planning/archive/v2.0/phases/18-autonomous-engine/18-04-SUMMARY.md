---
phase: 18-autonomous-engine
plan: 04
subsystem: testing
tags: [evals, fixtures, tick-brain, judgment, json-schema, pytest, AUTO-08]

# Dependency graph
requires:
  - phase: 18-autonomous-engine
    provides: "prompts/autonomous_triage.md (Plan 03 — defines situation_snapshot field expectations)"
provides:
  - "5 seed eval fixtures (one per trigger type plus quiet-evening negative) ready for scripts/eval_tick_brain.py (Plan 08)"
  - "Documented fixture schema + WARNING 8 followup rationale + retroactive labeling workflow in evals/tick_brain/README.md"
  - "tests/test_evals.py TestFixtureSchema (37 runs) — schema contract guard + WARNING 8 regression guard"
affects: [18-autonomous-engine Plan 06 (gather_situation must produce matching shape), 18-autonomous-engine Plan 08 (eval_tick_brain.py loads these fixtures)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Static JSON fixture schema validation via pytest.mark.parametrize over glob"
    - "Regression test pinning a single fixture's ground_truth value to guard against re-flipping (WARNING 8 pattern)"

key-files:
  created:
    - evals/tick_brain/README.md
    - evals/tick_brain/fixtures/0001-overdue-task.json
    - evals/tick_brain/fixtures/0002-quiet-evening.json
    - evals/tick_brain/fixtures/0003-due-followup.json
    - evals/tick_brain/fixtures/0004-long-silence.json
    - evals/tick_brain/fixtures/0005-calendar-gap.json
    - tests/test_evals.py
  modified: []

key-decisions:
  - "Fixture-per-file JSON (one fixture per file, name NNNN-slug.json) — composable, easy to add retroactively, git-friendly diffs"
  - "ground_truth.should_speak measures tick-brain (Layer 1) behavior only — orchestrator-level routing (followup-bypass, Layer 0 gate) does not influence fixture labels. Documented as 'What should_speak Means' section."
  - "topic_key_pattern is a regex (not literal) — allows fuzzy matching of the predicted slug while still catching category mistakes (e.g., overdue:* vs silence:*)"
  - "Test 9 (test_followup_only_fixture_expects_silence) is a regression guard distinct from the schema tests — fixture 0003 has structural validity but semantic correctness is the trap"

patterns-established:
  - "Pattern: greenfield eval harness — fixture directory + README + schema test, no harness code yet. Plan 08 consumes."
  - "Pattern: per-fixture parametrized validation — pytest.mark.parametrize(glob.glob(...)) yields one test per fixture, individually reported."

requirements-completed: [AUTO-08]

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 18 Plan 04: Eval Seed Fixtures Summary

**5 hand-written tick-brain eval fixtures (one per trigger type + quiet-evening negative), README documenting the schema/followup-rationale/retroactive-labeling workflow, and tests/test_evals.py TestFixtureSchema (37 parametrized runs including a WARNING 8 regression guard pinning 0003-due-followup to should_speak=false)**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-22T20:43:12Z
- **Completed:** 2026-05-22T20:46:06Z
- **Tasks:** 2
- **Files created:** 7

## Accomplishments

- 5 seed fixtures cover all four AUTO-04 trigger types (`overdue`, `gap`, `silence`, `followup`) plus the `quiet` obvious-negative
- `evals/tick_brain/README.md` (123 lines) documents the fixture schema in full, including the "What should_speak Means" section that warns future labelers off mis-labeling fixture 0003
- Retroactive-labeling workflow from `tick_logs/{date}/ticks/{HH:MM}` Firestore docs is documented end-to-end (export → inspect → copy → label → run pytest + eval)
- `tests/test_evals.py::TestFixtureSchema` (9 logical tests × parametrization = 37 runs) — all green
- WARNING 8 regression guard (`test_followup_only_fixture_expects_silence`) pins fixture 0003 to `should_speak=false`; cannot regress silently

## Task Commits

Each task was committed atomically:

1. **Task 1: Author README + 5 seed fixtures** — `3977bf6` (feat)
2. **Task 2: TestFixtureSchema schema-validation tests** — `01dbef8` (test)

**Plan metadata:** _(final docs commit below)_

## Files Created/Modified

### Created
- `evals/tick_brain/README.md` — fixture schema doc + WARNING 8 followup rationale + retroactive-labeling workflow (123 lines)
- `evals/tick_brain/fixtures/0001-overdue-task.json` — overdue TickTick task; should_speak=true; pattern `^overdue:.*`
- `evals/tick_brain/fixtures/0002-quiet-evening.json` — quiet evening, nothing salient; should_speak=false (obvious negative)
- `evals/tick_brain/fixtures/0003-due-followup.json` — due followup; **should_speak=false** per D-13 (followup bypasses tick-brain)
- `evals/tick_brain/fixtures/0004-long-silence.json` — 11.5h silence on a deep-work day; should_speak=true; pattern `^silence:.*`
- `evals/tick_brain/fixtures/0005-calendar-gap.json` — workout overlaps client call; should_speak=true; pattern `^gap:.*`
- `tests/test_evals.py` — TestFixtureSchema with 9 logical tests (parametrized to 37 runs)

### Modified
- `.planning/phases/18-autonomous-engine/deferred-items.md` — appended note about pre-existing `googleapiclient` ImportError in tests/test_tools.py (local env only; out of scope)

## Fixture Inventory

| File                          | Trigger  | should_speak | topic_key_pattern  |
| ----------------------------- | -------- | ------------ | ------------------ |
| 0001-overdue-task.json        | overdue  | true         | `^overdue:.*`      |
| 0002-quiet-evening.json       | quiet    | false        | —                  |
| 0003-due-followup.json        | followup | **false**    | —                  |
| 0004-long-silence.json        | silence  | true         | `^silence:.*`      |
| 0005-calendar-gap.json        | gap      | true         | `^gap:.*`          |

**WARNING 8 confirmation:** 0003 is `should_speak=false`. README's "What should_speak Means" section explains why (D-13: followup path bypasses tick-brain). Test `test_followup_only_fixture_expects_silence` in `tests/test_evals.py` regression-guards this.

## Decisions Made

- **Each fixture is its own JSON file** (vs. a single fixtures.json array) — easier to grow retroactively, cleaner git blame on per-fixture labels, the eval harness can glob the directory.
- **`topic_key_pattern` is a regex string** — allows fuzzy matching (`^overdue:.*` catches `overdue:reply-to-maya`, `overdue:weekly-review`, etc.) while still tripping on category mistakes.
- **`_note` field on ground_truth is documented as labeler-facing only** — eval code does not read it; it exists so 0003's surprising `should_speak=false` is self-explanatory inside the fixture file itself.
- **Followed plan as specified** — fixture content, README structure, and test set all match the plan body exactly. No deviations needed.

## Deviations from Plan

None — plan executed exactly as written. The plan was richly specified (full fixture JSON contents and test code inline), so execution was mechanical.

## Issues Encountered

- **Pre-existing local env issue (out of scope):** `tests/test_tools.py` fails to collect because `googleapiclient` is not installed in the local Python env. This affects neither the eval-fixture tests nor CI (Cloud Run image has the package). Logged in `.planning/phases/18-autonomous-engine/deferred-items.md`. The plan's regression-check requirement was satisfied by running `tests/test_prompts.py tests/test_firestore_db.py` (32/32 green); `tests/test_tools.py` failure is independent of Plan 18-04 changes.
- **Shell quirk:** `python` not on PATH locally; substituted `python3` for verification commands. Cosmetic only.

## Verification Results

All 5 plan-level verification commands pass:

1. `ls evals/tick_brain/fixtures/ | wc -l` → 5
2. `pytest tests/test_evals.py -v` → 37 passed
3. JSON-loadability check across all 5 fixtures → OK
4. `0003-due-followup.json ground_truth.should_speak is False` → OK
5. `grep -ci "what should_speak means" evals/tick_brain/README.md` → 1

## Self-Check: PASSED

- `evals/tick_brain/README.md` — exists (123 lines)
- `evals/tick_brain/fixtures/0001-overdue-task.json` — exists, valid JSON
- `evals/tick_brain/fixtures/0002-quiet-evening.json` — exists, valid JSON
- `evals/tick_brain/fixtures/0003-due-followup.json` — exists, should_speak=false confirmed
- `evals/tick_brain/fixtures/0004-long-silence.json` — exists, valid JSON
- `evals/tick_brain/fixtures/0005-calendar-gap.json` — exists, valid JSON
- `tests/test_evals.py` — exists, 37 tests green
- Commit `3977bf6` — present in `git log`
- Commit `01dbef8` — present in `git log`

## Next Phase Readiness

- **Plan 18-05 (Wave 2 — outreach_log + followup stores) and Plan 18-06 (gather_situation + run_autonomous_tick)** are unblocked. Plan 06 must produce a `situation_snapshot` dict whose top-level keys match the 9 keys validated by `tests/test_evals.py::test_each_situation_snapshot_has_required_keys` (`calendar`, `ticktick_overdue`, `unread_email_count`, `due_followups`, `hours_since_contact`, `recent_journal_digest`, `self_state`, `today_outreach_log`, `now_context`). The test will catch any future drift.
- **Plan 18-08 (eval_tick_brain.py)** has concrete day-one inputs to glob over. The 5 seeds let the harness boot and let the reporting code be tested against real shapes.
- **No blockers.**

---
*Phase: 18-autonomous-engine*
*Completed: 2026-05-22*
