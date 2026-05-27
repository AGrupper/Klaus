---
phase: 19-training-awareness-nutrition-coaching
plan: 04
subsystem: cron-tier-integration
status: completed
completed_at: 2026-05-27
tags: [autonomous-tick, morning-briefing, postgres-writeback, eval-fixtures, nutrition, training-status, acwr]
requires:
  - Plan 19-01 (Postgres schema: daily_biometrics columns vo2_max, resting_hr, hrv_*, sleep_*, body_battery_max, training_readiness)
  - Plan 19-02 (mcp_tools/garmin_tool.py::fetch_garmin_training_status / compute_acwr_from_db)
  - Plan 19-03 (mcp_tools/google_fit_tool.py::sync_recent_meals + memory/firestore_db.py::MealStore.get_day_aggregate Pitfall-4 empty-{} contract)
provides:
  - core/autonomous.py::gather_situation — 3 new gather sources (i/j/k) wired with per-source try/except (Pattern C)
  - core/autonomous.py::_is_empty_signals — meals_since_last_tick is now a trigger (NUTR-04); training_status + acwr are NOT triggers
  - core/autonomous.py::_build_triage_prompt + _compose_layer2 — JSON snapshots include 3 new keys (parity)
  - core/morning_briefing.py::_gather_data — nutrition recap (NUTR-05, silent-omit on empty per NUTR-07) + Postgres biometrics writeback (GARMIN-05)
  - mcp_tools/garmin_tool.py::write_today_biometrics_to_postgres — best-effort UPSERT helper for GARMIN-05
  - tests/test_evals.py::_REQUIRED_SNAPSHOT_KEYS — extended from 9 to 12 keys; 2 new tests guard the extension
affects:
  - Plan 19-05 (smart_agent.md + autonomous_triage.md + morning_briefing.md prompt extensions — will reference the 3 new gather keys via {meals_since_last_tick}, {training_status}, {acwr} placeholders)
  - Eval harness (scripts/eval_tick_brain.py): byte-for-byte triage prompt is now Phase-19-key-aware
tech-stack:
  added: []
  patterns:
    - "Pattern C (per-source try/except in gather): each of the 3 new sources lives in its own try/except → empty-default sentinel. One source's failure cannot mask the other 10."
    - "NUTR-04 trigger boundary: meals_since_last_tick IS a trigger (forces _is_empty_signals=False); training_status + acwr are CONTEXT only (never triggers — would over-fire the autonomous tick on high-ACWR days)."
    - "Pitfall 4 silent-omit in _gather_data: only assign data['nutrition'] = agg when truthy. Empty dict {} from MealStore.get_day_aggregate means 'no meals' — the prompt's silent-omit semantics depend on the KEY being absent, not on meal_count==0."
    - "GARMIN-05 best-effort writeback: write_today_biometrics_to_postgres swallows all exceptions internally; outer try/except in _gather_data is defense-in-depth. A Postgres outage cannot block the morning briefing."
    - "Pitfall 6 fixture schema lock: tests/test_evals.py::_REQUIRED_SNAPSHOT_KEYS extended in lock-step with gather_situation. All 5 seed fixtures updated in the same commit so the eval harness's triage prompt stays byte-for-byte identical to production."
key-files:
  created:
    - .planning/phases/19-training-awareness-nutrition-coaching/19-04-SUMMARY.md
  modified:
    - mcp_tools/garmin_tool.py (+71 lines: write_today_biometrics_to_postgres helper)
    - core/autonomous.py (+44 lines: 3 new gather sources i/j/k + 5-line _is_empty_signals extension + 5-line _build_triage_prompt snap extension + 5-line _compose_layer2 snap_summary extension)
    - core/morning_briefing.py (+30 lines: GARMIN-05 Postgres writeback block after Garmin source + NUTR-05/NUTR-07 nutrition recap block before return)
    - tests/test_garmin_extensions.py (+73 lines: 4 new tests for write_today_biometrics_to_postgres)
    - tests/test_autonomous.py (+115 lines: TestPhase19Gather class with 5 tests)
    - tests/test_morning_briefing.py (+134 lines: TestPhase19MorningBriefing class with 6 tests)
    - tests/test_evals.py (+22 lines: 3 keys added to _REQUIRED_SNAPSHOT_KEYS + 2 new tests at module level)
    - evals/tick_brain/fixtures/0001-overdue-task.json (+3 lines: empty defaults for 3 new keys)
    - evals/tick_brain/fixtures/0002-quiet-evening.json (+3 lines)
    - evals/tick_brain/fixtures/0003-due-followup.json (+3 lines; ground_truth.should_speak preserved as false — WARNING 8 regression guard intact)
    - evals/tick_brain/fixtures/0004-long-silence.json (+3 lines)
    - evals/tick_brain/fixtures/0005-calendar-gap.json (+3 lines)
decisions:
  - "Phase 19 fixture filenames retained as-is (0001-overdue-task.json, 0002-quiet-evening.json, 0003-due-followup.json, 0004-long-silence.json, 0005-calendar-gap.json). The plan text named different filenames (0002-calendar-gap.json, etc.) but the live filenames from Phase 18-04 are what tests/test_evals.py::test_id_matches_filename_stem already locks. Renaming would have triggered cascading regressions; the schema extension is decoupled from filenames."
  - "ACWR sentinel choice: gather_situation falls back to {\"ratio\": None} on source failure rather than {} so triage prompts and downstream prompts (Plan 19-05) can always check `acwr.get('ratio')` without a KeyError. compute_acwr_from_db's own internal sentinel is {acute: 0.0, chronic: None, ratio: None} — also includes ratio key."
  - "Eval fixture defaults use {\"acute\": null, \"chronic\": null, \"ratio\": null} rather than {} for acwr. This matches the production sentinel shape from compute_acwr_from_db when Postgres is empty (no activities in the 28-day window). Keeps fixtures realistic — a quiet 8 PM tick on a recovery day really would carry this exact ACWR shape."
  - "fetch_garmin_today's `sleep_duration` (REAL) used directly in Postgres writeback — matches daily_biometrics column type from Phase 19-01 schema (NUMERIC(4,2)). psycopg2 coerces float → NUMERIC implicitly."
  - "Morning briefing Postgres writeback fires AFTER the garmin fetch and BEFORE the TickTick fetch — chosen position keeps the writeback temporally close to the data source and means a write failure (which is best-effort anyway) doesn't impact downstream sources."
  - "_is_empty_signals extension: only meals_since_last_tick is added as a trigger. training_status and acwr are context-only — adding them as triggers would force a speak-up on every single tick where the operator has training data (i.e. every tick). Decision documented in code comment."
metrics:
  duration: "~50 min (4 tasks, RED→GREEN TDD per task)"
  tasks: 4
  files: 12
  commits: 7  # 6 code (3 RED + 3 GREEN) + 1 combined for schema+fixtures
---

# Phase 19 Plan 04: Autonomous Tick + Morning Briefing Phase-19 Integration — Summary

Plans 19-02 and 19-03 built the data layer (Garmin live reads + MealStore + Postgres ACWR). This plan wires it into Klaus's two cron-tier consumers: the autonomous tick gathers meals + training_status + ACWR every 20 minutes (NUTR-04, with the strict trigger-vs-context boundary so context never over-fires the brain); the morning briefing surfaces yesterday's nutrition aggregate when meals exist (NUTR-05 with NUTR-07 silent-omit) and writes today's fresh biometrics back to Postgres best-effort (GARMIN-05). The eval fixture schema lock is extended in lock-step (Pitfall 6) so the eval harness's triage prompt stays byte-for-byte identical to production. Phase 19 progress: 4/5 plans.

## What shipped

### Code

| File | Change |
|---|---|
| `mcp_tools/garmin_tool.py` | `write_today_biometrics_to_postgres(garmin)` (+71 lines): lazy psycopg2 import; UPSERT to `daily_biometrics` with `ON CONFLICT (date) DO UPDATE SET`; reads `DATABASE_URL` or `PG_CONNECTION_STRING` (latter for test parity with `compute_acwr_from_db`); all exception paths return None silently with logger.warning. |
| `core/autonomous.py::gather_situation` | 3 new sources after (h) outreach_log: (i) meals via `sync_recent_meals(since_hours=1, store=MealStore)` → `meals_since_last_tick`; (j) Garmin training status → `training_status`; (k) `compute_acwr_from_db()` → `acwr`. Each in its own try/except → empty-default sentinel (Pattern C). |
| `core/autonomous.py::_is_empty_signals` | New 5-line branch: `if situation.get("meals_since_last_tick"): return False`. Code comment explicitly documents that `training_status` and `acwr` are context-only — not triggers (NUTR-04 boundary). |
| `core/autonomous.py::_build_triage_prompt` | snap dict extended with 3 new keys: `meals_since_last_tick`, `training_status`, `acwr` (with empty defaults via `.get(..., default)`). |
| `core/autonomous.py::_compose_layer2` | snap_summary dict extended identically — parity with triage so the brain's compose layer sees the same context the tick-brain saw at triage. |
| `core/morning_briefing.py::_gather_data` | Two new blocks: (1) GARMIN-05 writeback — calls `write_today_biometrics_to_postgres(data["garmin"])` only when `garmin.state == 1` (today's data present), wrapped in defense-in-depth try/except; (2) NUTR-05 nutrition recap — reads `MealStore.get_day_aggregate(yesterday)` and writes `data["nutrition"] = agg` ONLY when truthy (NUTR-07 silent-omit). |

### Tests

| Test file | New | Status |
|---|---|---|
| `tests/test_garmin_extensions.py::test_write_today_biometrics_*` | 4 | ✅ |
| `tests/test_autonomous.py::TestPhase19Gather` | 5 | ✅ |
| `tests/test_morning_briefing.py::TestPhase19MorningBriefing` | 6 | ✅ |
| `tests/test_evals.py::test_phase19_fixture_*` | 2 | ✅ |
| **Full project suite** | **557 passed, 3 skipped** | ✅ (was 540 baseline → +17 net, 0 regressions) |

### Eval fixtures (5 files, +3 lines each)

| Fixture | Change | should_speak preserved? |
|---|---|---|
| `0001-overdue-task.json` | Added empty defaults for `meals_since_last_tick`, `training_status`, `acwr` | n/a (was true) |
| `0002-quiet-evening.json` | Same | n/a (was false) |
| `0003-due-followup.json` | Same | ✅ **false** (WARNING 8 regression guard intact — `test_followup_only_fixture_expects_silence` still passes) |
| `0004-long-silence.json` | Same | n/a (was true) |
| `0005-calendar-gap.json` | Same | n/a (was true) |

## Commits (chronological)

| Commit | Type | Description |
|---|---|---|
| `388f0a5` | test(19-04) | RED — 4 failing tests for `write_today_biometrics_to_postgres` |
| `8801a42` | feat(19-04) | GREEN — `write_today_biometrics_to_postgres` best-effort helper |
| `874eed8` | test(19-04) | RED — 5 failing tests for autonomous Phase 19 gather + triage extensions |
| `293cda0` | feat(19-04) | GREEN — extend autonomous gather/triage/compose with meals + training_status + acwr (NUTR-04) |
| `7a7994b` | test(19-04) | RED — 6 failing tests for morning_briefing Phase 19 nutrition recap + Postgres writeback |
| `85aded5` | feat(19-04) | GREEN — morning briefing reads yesterday's meals + writes biometrics to Postgres (NUTR-05, GARMIN-05) |
| `0334747` | feat(19-04) | Eval fixture schema lock + 5 seed fixtures with Phase 19 keys (Pitfall 6) — single commit, test-only |

## Deviations from Plan

### Auto-fixed (Rule 1, in-scope)

**1. Fixture filenames differ from the plan text**
- **Issue:** Plan's `files_modified` listed `0001-overdue-tasks.json`, `0002-calendar-gap.json`, `0003-due-followup.json`, `0004-quiet-no-signal.json`, `0005-stale-contact.json`. Live filenames (from Phase 18-04) are `0001-overdue-task.json`, `0002-quiet-evening.json`, `0003-due-followup.json`, `0004-long-silence.json`, `0005-calendar-gap.json`.
- **Fix:** Schema extension applied to the live filenames. The plan's intent (extend each of the 5 fixtures with 3 new keys + empty defaults) was honored; the filenames in the plan were the drift — `test_id_matches_filename_stem` already locks the live names so renaming would have triggered cascading regressions.
- **Why in-scope:** Plan listed filenames as a convenience reference; the load-bearing contract is "all 5 seed fixtures carry the 3 new keys". `test_phase19_all_fixtures_have_new_keys` enforces that contract by globbing the fixtures directory rather than referencing filenames literally.

### Deferred (out of scope)

None new in this plan. Existing deferred items from 19-01 remain in `deferred-items.md`.

## NUTR-04 / NUTR-05 / GARMIN-05 Acceptance

| Req | Statement | Evidence |
|---|---|---|
| NUTR-04 | Autonomous-tick layer-0 syncs Fit → MealStore + includes meals-since-last-tick in triage context | `gather_situation` source (i) calls `sync_recent_meals(since_hours=1, store=MealStore)`; `_is_empty_signals` returns False when `meals_since_last_tick` is non-empty (verified by `test_meal_in_meals_since_last_tick_makes_signals_not_empty`); `_build_triage_prompt` and `_compose_layer2` both include the key in their JSON snapshots (verified by `test_triage_prompt_includes_phase19_keys`). |
| NUTR-05 | Morning-briefing `_gather_data()` aggregates yesterday's meals (totals + breakdown + biggest gap) | `_gather_data` calls `MealStore.get_day_aggregate(yesterday)` and writes `data["nutrition"] = agg` (verified by `test_aggregates_yesterday_meals`). NUTR-07 silent-omit precondition enforced: empty `{}` → no `nutrition` key (verified by `test_no_nutrition_key_when_empty`). |
| GARMIN-05 | Morning-briefing `_gather_data()` writes fresh biometrics to Postgres (best-effort) | `_gather_data` calls `write_today_biometrics_to_postgres(data["garmin"])` only when `garmin.state == 1` (verified by `test_writes_biometrics_to_postgres` + `test_writeback_skipped_when_garmin_state_2`). Postgres outage swallowed: verified by `test_postgres_outage_does_not_block_briefing`. |

All three requirements: **SATISFIED**.

## TDD Gate Compliance

3 RED commits precede 3 GREEN commits for Tasks 1–3 (`388f0a5 → 8801a42`, `874eed8 → 293cda0`, `7a7994b → 85aded5`). Task 4 (schema lock + fixture updates) ships as a single feat commit because it's test-only — the schema extension and fixture defaults must land atomically or `test_each_situation_snapshot_has_required_keys` fails on every fixture; not amenable to separate RED/GREEN.

## Self-Check: PASSED

- ✅ `core/autonomous.py::gather_situation` contains all 3 new sources (i/j/k) — verified by grep: `meals_since_last_tick`, `training_status`, `acwr` each appear in the file
- ✅ `core/autonomous.py::_is_empty_signals` checks `meals_since_last_tick` and explicitly documents that `training_status` + `acwr` are NOT triggers
- ✅ `core/autonomous.py::_build_triage_prompt` and `_compose_layer2` both include the 3 new keys (`grep -c "meals_since_last_tick" core/autonomous.py` returns 4 — 1 gather + 1 _is_empty_signals + 1 triage + 1 compose)
- ✅ `core/morning_briefing.py::_gather_data` contains the Postgres writeback block and the nutrition recap block, in that order
- ✅ `mcp_tools/garmin_tool.py::write_today_biometrics_to_postgres` exists with `INSERT INTO daily_biometrics ... ON CONFLICT (date) DO UPDATE SET`
- ✅ `tests/test_evals.py::_REQUIRED_SNAPSHOT_KEYS` has 12 entries
- ✅ All 5 seed fixtures contain `meals_since_last_tick: []`, `training_status: {}`, `acwr: {"acute": null, "chronic": null, "ratio": null}`
- ✅ Fixture 0003-due-followup.json's `ground_truth.should_speak` is still `false` (WARNING 8 regression guard intact)
- ✅ All 7 commits reachable in `git log`: 388f0a5, 8801a42, 874eed8, 293cda0, 7a7994b, 85aded5, 0334747
- ✅ Full test suite: **557 passed, 3 skipped** (was 540 baseline → +17 net, 0 regressions)
