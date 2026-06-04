---
phase: 21-living-plan-ingestion
plan: "02"
subsystem: tools
tags: [tools, training-profile, update-plan, json-safety, tdd]
dependency_graph:
  requires: ["21-01"]
  provides: ["update_plan alias", "JSON-safe get_training_profile", "v4.0 schema advertisement"]
  affects: ["core/tools.py", "tests/test_tools.py"]
tech_stack:
  added: []
  patterns: ["_jsonsafe_doc for DatetimeWithNanoseconds ISO-conversion", "tool alias via _HANDLERS lambda"]
key_files:
  created: []
  modified:
    - core/tools.py
    - tests/test_tools.py
decisions:
  - "update_plan is a thin alias — same _handle_update_training_profile handler; no logic duplication"
  - "JSON safety via _jsonsafe_doc import (not inline pop) — reuses the established firestore_db helper"
  - "update_plan added to SMART_AGENT_DIRECT_TOOLS so the brain calls it directly, not via worker"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-04"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 2
---

# Phase 21 Plan 02: Update Path Extension + JSON-Safe Get Handler Summary

**One-liner:** Extended `update_training_profile` schema with 6 v4.0 structured keys, added `update_plan` brain-direct alias via `_HANDLERS`, and closed the `DatetimeWithNanoseconds` serialization latent bug in `_handle_get_training_profile` using `_jsonsafe_doc`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for update_plan + JSON-safe get | 0919775 | tests/test_tools.py |
| 1 (GREEN) | Extend update schema, add update_plan alias, JSON-safe get handler | f0a27f5 | core/tools.py |

## What Was Built

### core/tools.py — Three changes

1. **`update_training_profile` schema extended**: Both the tool `description` and the `patch` property description now list all 9 recognized top-level keys — the original 3 (`athletic_goals`, `training_constraints`, `recovery_preferences`) plus the 6 new v4.0 structured fields (`dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, `plan_start_date`). The brain now knows all valid keys and will emit them in patches.

2. **`update_plan` tool added**: New schema entry (brain-direct, clones the `update_training_profile` shape with a user-facing description). Registered in:
   - `SMART_AGENT_DIRECT_TOOLS` (brain calls it directly, not via worker)
   - `TOOL_SCHEMAS` (schema list for all tools)
   - `_HANDLERS` dispatch as `lambda args: _handle_update_training_profile(**args)` — same underlying handler, zero code duplication

3. **`_handle_get_training_profile` JSON-safe**: Changed `return json.dumps(store.load())` to `return json.dumps(_jsonsafe_doc(store.load()))`. Imports `_jsonsafe_doc` from `memory.firestore_db` (the same helper used by `TrainingLogStore` and `BlockStore`). This closes threat T-21-04 — a real `updated_at: DatetimeWithNanoseconds` from Firestore would have raised `TypeError` on the first `get_training_profile` call after the blueprint ingest.

### tests/test_tools.py — 9 new tests (class `TestPhase21UpdatePlanAlias`)

- `test_update_plan_in_handlers` — `_HANDLERS["update_plan"]` exists
- `test_update_plan_in_smart_agent_direct_tools` — brain-direct registration
- `test_update_plan_schema_registered` — TOOL_SCHEMAS entry
- `test_update_plan_schema_requires_patch` — patch is required arg
- `test_update_plan_calls_store_update` — dispatch wires to `store.update()`
- `test_update_plan_new_structured_key_passes_through` — no allow-list rejection for `dated_goals`
- `test_update_plan_and_update_training_profile_identical_writes` — both aliases produce same Firestore writes
- `test_get_training_profile_json_safe_with_datetime` — handler returns valid JSON when `updated_at` is a `datetime`; ISO-converted to `str`
- `test_update_training_profile_schema_has_new_keys` — schema description advertises all 6 new keys

## Verification

```
pytest tests/test_tools.py -x -q
33 passed in 0.14s
```

All 33 tests pass (24 pre-existing + 9 new).

## Deviations from Plan

None — plan executed exactly as written. Both tasks followed TDD: RED (failing tests committed first), then GREEN (implementation to pass).

## Known Stubs

None. The `update_plan` alias is fully wired to the production merge-write handler. The JSON-safe fix is a real fix, not a stub.

## Threat Flags

None. T-21-04 (the `DatetimeWithNanoseconds → json.dumps TypeError`) was the only flagged mitigation for this plan and has been closed by the `_jsonsafe_doc` import in `_handle_get_training_profile`.

## Self-Check: PASSED

- FOUND: .planning/phases/21-living-plan-ingestion/21-02-SUMMARY.md
- FOUND: core/tools.py
- FOUND: tests/test_tools.py
- FOUND commit: 0919775 (RED — failing tests)
- FOUND commit: f0a27f5 (GREEN — implementation)
