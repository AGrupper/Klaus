---
phase: 21-living-plan-ingestion
plan: "03"
subsystem: data-ingest
tags: [blueprint-ingest, firestore, seed-script, tdd, profile-v4]
dependency_graph:
  requires: ["21-01"]
  provides: ["scripts/ingest_blueprint.py", "tests/test_ingest_blueprint.py"]
  affects: ["memory/firestore_db.py UserProfileStore (users/amit write target)"]
tech_stack:
  added: []
  patterns:
    - "Pure function build_profile_dict() with no Firestore/env dependencies"
    - "Idempotency gate via plan_start_date presence check"
    - "load_dotenv(override=True) invariant"
    - "lazy Firestore import guarded behind --dry-run early-return"
key_files:
  created:
    - scripts/ingest_blueprint.py
    - tests/test_ingest_blueprint.py
  modified: []
decisions:
  - "Transcribed blueprint content into Python literals rather than parsing prose Markdown (more stable; blueprint is small and versioned)"
  - "Section 4 (16-week aerobic table) stored as a single aerobic_reference_note string in nutrition_targets — never as 16 tracked target rows"
  - "main() co-implemented with build_profile_dict() in one pass (TDD test commit first, then implementation commit)"
  - "UserProfileStore lazy-imported inside the non-dry-run branch so --dry-run never instantiates a Firestore client"
metrics:
  duration_minutes: 20
  completed_date: "2026-06-04"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 21 Plan 03: Blueprint Ingest Script Summary

**One-liner:** Idempotent `scripts/ingest_blueprint.py` that builds the v4.0 structured profile dict from `docs/hybrid_athlete_blueprint.md` and writes it to Firestore `users/amit` via `UserProfileStore.update(merge=True)`, with `--dry-run` / `--force` flags and a 22-test pure-function test suite.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| TDD RED | Failing tests for build_profile_dict | 3044462 | tests/test_ingest_blueprint.py |
| 1 (GREEN) | build_profile_dict + main() implementation | 8964ce2 | scripts/ingest_blueprint.py |
| 2 | CLI wiring verified (co-impl in Task 1) | 8964ce2 | scripts/ingest_blueprint.py |

## What Was Built

### `scripts/ingest_blueprint.py`

A one-time seed script with:

- **`build_profile_dict() -> dict`** — pure function, no env or Firestore. Returns the six v4.0 structured keys:
  - `dated_goals`: Oct peak (100kg bench, 120kg squat, 1:25 HM target 2026-10-31) + Nov peak (125 push-ups, 35 pull-ups, 9:30 3k, 55s 400m target 2026-11-30). Tier A targets only — no current-performance baselines.
  - `weekly_split`: 7-day AM/PM session template from Section 2. Each session has `label`, `modality`, `priority`. No `done`/`completed`/`attended`/`attendance` keys.
  - `nutrition_targets`: `protein_g=150`, `carbs_g=350`, 6 fueling slot labels, and a loose `aerobic_reference_note` string (Section 4 — not stored as 16 tracked target rows).
  - `fueling_timeline`: 6 ordered slot dicts (pre-am-run → post-am-run → mid-day → pm-pre-lift → pm-post-lift → pre-bed).
  - `supplement_schedule`: 4 supplement-to-slot mappings (D3+K2/Omega3 → post-am-run; Beta-Alanine → pm-pre-lift; Creatine → pm-post-lift; Mg Glycinate/Zinc/Copper → pre-bed).
  - `plan_start_date`: `"2026-06-21"` (Block Week 1 anchor for Phase 23).

- **`main()`** — CLI entry with `--dry-run` (print JSON, no write) and `--force` (re-ingest over existing v4.0 fields). Idempotency gate: without `--force`, script declines to overwrite when `plan_start_date` already present. `UserProfileStore` import is lazy-guarded behind the `--dry-run` early return (T-21-07 mitigation). `sys.exit(1)` on any exception.

### `tests/test_ingest_blueprint.py`

22 tests across 7 test classes:
- `TestTopLevelKeys`: all 6 keys present, `plan_start_date` correct, no baseline keys
- `TestDatedGoals`: list structure, Oct/Nov peak metrics, `target_date`/`goal_label`/`metrics` shape
- `TestWeeklySplit`: 7 days, AM/PM sessions, `label`/`modality`/`priority` keys, no attendance booleans
- `TestNutritionTargets`: `protein_g=150`, `carbs_g=350`, no 16-week table entries
- `TestFuelingTimeline`: 6 slots, `slot`+`food` keys, pre-am-run first, pre-bed last
- `TestSupplementSchedule`: `slot`+`items` keys, Creatine/Beta-Alanine/Magnesium present
- `TestNo16WeekTable`: recursive check that no list of exactly 16 items exists in the payload

## Verification Results

```
python -m pytest tests/test_ingest_blueprint.py -x -q
22 passed in 0.01s

python -c "...six-key check..." → OK
python -c "...no-attendance check..." → no-attendance OK

python scripts/ingest_blueprint.py --dry-run | python -c "...json validation..."
→ dry-run OK (no GCP_PROJECT_ID required)
```

## Threat Mitigations

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-21-06: Re-run clobbers user-edited data | Idempotency gate: declines to write when `plan_start_date` already present unless `--force` passed | Implemented |
| T-21-07: Dry-run accidentally writes | `--dry-run` returns early before any Firestore client construction | Implemented + verified (no GCP creds needed) |

## Locked Narrowings Honored

1. **No 16-week aerobic table as tracked targets**: Section 4 stored as `aerobic_reference_note` string only — explicitly asserted by `TestNutritionTargets::test_no_16_week_table` and `TestNo16WeekTable::test_no_16_weekly_pace_volume_rows`.
2. **No current-performance baselines**: `dated_goals` holds Tier A targets only — `TestTopLevelKeys::test_no_current_performance_baseline_keys` asserts no `current_bench`, `current_pace`, `baseline` keys exist.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (test commit) | 3044462 | test(21-03): add failing tests for build_profile_dict pure function |
| GREEN (impl commit) | 8964ce2 | feat(21-03): implement build_profile_dict pure function for blueprint ingest |

## Deviations from Plan

**1. [Rule — Co-implementation] main() written with build_profile_dict() in one pass**

- **Found during:** Task 1 TDD implementation
- **Issue:** Task 2 was specified as a separate modification of `scripts/ingest_blueprint.py` to add `main()`, but the TDD GREEN phase naturally implements the full file including the CLI entry point.
- **Fix:** Both tasks implemented in one file in the Task 1 GREEN commit. Task 2 acceptance criteria were all verified against the same file. No separate code change needed for Task 2.
- **Impact:** Zero — all Task 2 acceptance criteria pass. The separation was a planning artifact; the implementation is correct.

## Known Stubs

None. All six structured keys are fully populated with blueprint-derived content.

## Threat Flags

None. The script writes to an existing Firestore document (`users/amit`) via `UserProfileStore.update(merge=True)` — already in the plan's threat model. No new trust boundaries introduced.

## Self-Check: PASSED

- [x] `scripts/ingest_blueprint.py` exists and is committed (8964ce2)
- [x] `tests/test_ingest_blueprint.py` exists and is committed (3044462 + 8964ce2)
- [x] 22 tests pass
- [x] `--dry-run` emits valid JSON with plan_start_date 2026-06-21
- [x] No 16-week target table in payload
- [x] No current-performance baselines
- [x] `load_dotenv(override=True)` present
- [x] Commits 3044462 and 8964ce2 exist on branch worktree-agent-a7586279f7788e695
