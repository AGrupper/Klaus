---
phase: 21-living-plan-ingestion
plan: "01"
subsystem: memory
tags: [firestore, user-profile, schema, tdd, v4.0]
dependency_graph:
  requires: []
  provides:
    - "UserProfileStore._SCAFFOLD v4.0 structured contract"
    - "schema_version 2"
    - "Field-name contract for Plans 02–04 (ingest, tool handler, renderer)"
  affects:
    - "memory/firestore_db.py UserProfileStore"
    - "tests/test_user_profile_store.py"
tech_stack:
  added: []
  patterns:
    - "TDD RED/GREEN for schema expansion"
    - "SelfStateStore discipline: reads never raise, writes re-raise, bootstrap never raises"
    - "Tier A (blueprint targets) vs Tier B (Garmin actuals) data separation"
key_files:
  created:
    - "tests/test_user_profile_store_v4_scaffold.py"
  modified:
    - "memory/firestore_db.py"
    - "tests/test_user_profile_store.py"
decisions:
  - "weekly_split scaffold default is empty dict — structurally prevents attendance/done/completed boolean keys (PLAN-02 rigidity-drift guard)"
  - "athletic_goals retained alongside dated_goals — weekly_training_review.py:188 reads it directly"
  - "training_constraints and recovery_preferences kept for forward-compat (no breaking removals)"
  - "schema_version bumped 1 → 2; load/update/bootstrap_if_empty method bodies unchanged"
metrics:
  duration_minutes: 3
  completed_date: "2026-06-04"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 21 Plan 01: UserProfileStore v4.0 Schema Expansion Summary

**One-liner:** Expanded `UserProfileStore._SCAFFOLD` from v1 generic stub to v4.0 structured contract with six dedicated fields (`dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, `plan_start_date`) and `schema_version` bumped to 2, establishing the field-name contract for downstream plans 02-04.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED  | Failing v4.0 scaffold tests | f5b75b7 | tests/test_user_profile_store_v4_scaffold.py (new, 164 lines) |
| 1    | Expand _SCAFFOLD to v4.0 contract | e6b8997 | memory/firestore_db.py |
| 2    | Update test assertions for v4.0 | 3a193af | tests/test_user_profile_store.py |

## What Was Built

**`memory/firestore_db.py`** — `UserProfileStore._SCAFFOLD` now contains:
- `dated_goals: []` — Tier A peak targets (Oct: 100kg bench/120kg squat/1:25 HM, Nov: 125 push-ups/35 pull-ups/9:30 3k/55s 400m), populated by ingest_blueprint.py in Plan 02
- `weekly_split: {}` — flexible AM/PM session template keyed by day; NO attendance/done/completed booleans (PLAN-02 rigidity-drift guard is structurally enforced by the empty-dict default)
- `nutrition_targets: {}` — daily macro targets dict
- `supplement_schedule: []` — ordered supplement slots list
- `fueling_timeline: []` — ordered 6-slot fueling architecture list
- `plan_start_date: ""` — ISO date "2026-06-21" (Block Week 1 anchor, set by Plan 02)
- `schema_version: 2` (was 1)
- Legacy fields retained: `athletic_goals` (Sunday cron reads it), `training_constraints`, `recovery_preferences`

The class docstring was expanded to enumerate all structured fields, document the Tier A (blueprint targets) vs Tier B (measured Garmin actuals) data discipline, and flag the `weekly_split` template invariant.

`load()`, `update()`, and `bootstrap_if_empty()` method bodies are unchanged — the `merge=True` + `SERVER_TIMESTAMP` discipline is unaffected.

**`tests/test_user_profile_store.py`** — Updated:
- `test_bootstrap_creates_when_missing`: asserts `schema_version == 2` (was 1)
- `test_bootstrap_seeds_v4_structured_keys`: new — verifies all six v4.0 keys present in bootstrapped doc
- `test_bootstrap_seeds_weekly_split_as_empty_dict`: new — PLAN-02 guard test, asserts `weekly_split == {}` (template shape, not attendance flags)

**`tests/test_user_profile_store_v4_scaffold.py`** — New RED-phase test file (10 tests) asserting _SCAFFOLD shape directly; kept as a standalone regression guard.

## Verification

All acceptance criteria met:
- `_SCAFFOLD` introspection confirms six structured keys + `schema_version == 2` + `athletic_goals` retained
- `grep -n "schema_version.*2" memory/firestore_db.py` matches inside `_SCAFFOLD`
- No attendance/done/completed boolean key near `_SCAFFOLD`
- `python3 -m pytest tests/test_user_profile_store.py -x -q` exits 0 (10 passed)
- `python3 -m pytest tests/test_user_profile_store_v4_scaffold.py -x -q` exits 0 (10 passed)
- `python3 -m pytest tests/test_firestore_db.py -x -q` exits 0 — no regressions (21 passed)

## TDD Gate Compliance

- RED gate: commit `f5b75b7` — `test(21-01): add failing RED tests for v4.0 UserProfileStore _SCAFFOLD` (10 tests, all failed against v1 scaffold)
- GREEN gate: commit `e6b8997` — `feat(21-01): expand UserProfileStore._SCAFFOLD to v4.0 structured contract`
- Task 2 GREEN gate: commit `3a193af` — `feat(21-01): update test_user_profile_store.py for v4.0 scaffold`

## Deviations from Plan

None — plan executed exactly as written.

The `test_user_profile_store_v4_scaffold.py` file was created as a separate RED-phase test file (per TDD protocol) and kept as a standalone regression guard. The plan described a single TDD cycle but the RED tests were naturally grouped into a dedicated file. Both the RED file and the updated `test_user_profile_store.py` are committed.

## Threat Surface Scan

No new threat surface introduced. This plan only changes an in-process constant (`_SCAFFOLD`) and tests. No new untrusted input crosses any boundary. Consistent with the plan's threat model: T-21-01 (bootstrap only writes when doc is absent — idempotent gate) and T-21-02 (bootstrap never raises — startup safety intact) are both satisfied unchanged.

## Known Stubs

`plan_start_date: ""` — intentionally empty. The canonical value "2026-06-21" will be written by `scripts/ingest_blueprint.py` (Plan 02). This is by design: Plan 01 establishes the field-name contract; Plan 02 populates it.

## Self-Check: PASSED
