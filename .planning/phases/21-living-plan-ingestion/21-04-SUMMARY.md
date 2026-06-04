---
phase: 21-living-plan-ingestion
plan: "04"
subsystem: prompt-rendering
tags: [training-profile, coaching-reference, render-smart-system, prompt-reframe, regression-guard]
dependency_graph:
  requires: ["21-01"]
  provides: ["coaching-reference prose in system prompt", "reframed TRAINING section", "v3.0 cron regression verified"]
  affects: ["core/main.py render_smart_system", "prompts/smart_agent.md", "tests/test_main_render_smart_system.py", "tests/test_weekly_training_review.py"]
tech_stack:
  added: []
  patterns: ["field-by-field conditional-append prose rendering (self_state analog)", "TDD RED/GREEN cycle", "forward-compat fallback for unknown keys"]
key_files:
  created: []
  modified:
    - core/main.py
    - prompts/smart_agent.md
    - tests/test_main_render_smart_system.py
    - tests/test_weekly_training_review.py
decisions:
  - "Replaced raw k:v dump with field-by-field prose renderer following self_state pattern"
  - "weekly_split renders label/modality/priority per AM/PM slot — no boolean source field exists so attendance flags are structurally impossible"
  - "Unknown/future keys fall through to generic '- k: v' fallback (forward-compat)"
  - "morning_briefing.py and proactive_alerts.py confirmed to NOT read UserProfileStore — zero code change needed for cron regression"
  - "Updated existing Phase 19 test expectation to expect new coaching-reference header (correct: behavior intentionally changed)"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-04"
  tasks_completed: 3
  files_changed: 4
---

# Phase 21 Plan 04: Coaching-Reference Rendering & Prompt Reframe Summary

**One-liner:** Prose coaching-reference renderer for structured profile fields in render_smart_system, reframed prompt section with Tier A/B discipline and weekly_split-as-template rule, v3.0 cron regression verified test-backed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED | Failing tests for coaching-reference rendering | 830ee8c | tests/test_main_render_smart_system.py |
| 1 GREEN | Coaching-reference prose rendering in render_smart_system | ef8f560 | core/main.py, tests/test_main_render_smart_system.py |
| 2 | Reframe TRAINING & ATHLETIC COACHING prompt section | 96b48f8 | prompts/smart_agent.md |
| 3 | v3.0 cron-regression guard tests | e2b5b45 | tests/test_weekly_training_review.py |

## What Was Built

### Task 1: Coaching-reference prose rendering (core/main.py)

Replaced the generic `for k, v: "- {k}: {v}"` dump in `render_smart_system` with field-by-field coaching-reference prose:

- **Header:** `**Coaching reference — Amit's training plan:**`
- **`dated_goals`:** one bullet per goal — `label (target_date): metric1, metric2`
- **`weekly_split`:** per-day AM/PM lines — `Day: AM label [modality] · priority / PM label [modality] · priority`. No boolean source field → attendance flags structurally impossible.
- **`nutrition_targets`:** `Daily targets: Xg protein / Yg carbs` + optional fueling slots line
- **`fueling_timeline`:** ordered `Slot N — timing: food` lines
- **`supplement_schedule`:** ordered `slot: item1, item2` lines
- **`plan_start_date`:** `Block anchor: YYYY-MM-DD (Block Week 1)`
- **Forward-compat fallback:** any key not in the known set renders as `- k: v`
- **Preserved:** `non_empty` guard, `updated_at/bootstrapped_at/schema_version` exclusion filter, empty-profile → empty-snippet behavior

9 new tests cover all structured keys, the no-attendance-words guard, the unknown-key fallback, meta-key exclusion, and empty-profile behavior. All 21 tests in `test_main_render_smart_system.py` pass.

### Task 2: TRAINING & ATHLETIC COACHING section reframe (prompts/smart_agent.md)

Rewrote the section in place (lines 77–99) to:
- Describe each structured key and its semantic role
- Add explicit `weekly_split is a template, not a contract — never nag about a single missed session`
- Add Tier A vs Tier B data discipline block (targets in profile vs measured actuals from Garmin/TrainingLogStore)
- Name `update_plan` as user-facing update tool (with `update_training_profile` alias)
- Extend recognized update keys to all structured fields
- Preserve and extend `do NOT invent` discipline to all structured fields
- Add `never silently rewrites` clause
- Remove Google Fit reference (deprecated; HealthKit is the live source)
- `{training_profile}` placeholder at line 7 unchanged

### Task 3: v3.0 cron-regression verification

**morning_briefing.py and proactive_alerts.py:** `grep -rn "UserProfileStore\|training_profile"` returns empty — neither file reads the user profile. No code change needed. These crons consume Garmin/weather/calendar data, not the training profile.

**weekly_training_review.py:** Confirmed `profile.get("athletic_goals") or []` at line 188 — safe `.get()` with default, `athletic_goals` key retained in v4.0 scaffold by Plan 01. Added two regression tests:
1. `test_weekly_review_athletic_goals_from_full_v4_schema`: full v4.0 profile with all new structured keys → `athletic_goals` resolves correctly, no exception
2. `test_weekly_review_athletic_goals_absent_in_v4_schema`: v4.0 profile without `athletic_goals` key → returns `[]` via `.get()` default, no KeyError

All 7 tests in `test_weekly_training_review.py` pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Phase 19 test expected old "Training profile:" header**
- **Found during:** Task 1 GREEN phase
- **Issue:** `TestPhase19TrainingProfile.test_training_profile_substituted` asserted `"**Training profile:**" in result` — this was the old header that Plan 04 intentionally replaces
- **Fix:** Updated assertion to `"**Coaching reference — Amit's training plan:**"` with a comment noting the Phase 21 change
- **Files modified:** tests/test_main_render_smart_system.py
- **Commit:** ef8f560

## morning_briefing / proactive_alerts Profile Read Status

`grep -rn "UserProfileStore\|training_profile" core/morning_briefing.py core/proactive_alerts.py` → **no matches**

Both crons are unaffected by the profile expansion. They read Garmin activity data, weather, and calendar — not `UserProfileStore`. No defensive code changes were needed.

## Verification Results

```
python -m pytest tests/test_main_render_smart_system.py tests/test_weekly_training_review.py -x -q
28 passed in 0.26s
```

Prompt grep gates:
- `template, not a contract` / `never nag about a single missed session` — present
- `Tier A` / `Tier B` — present
- `update_plan` — present (lines 116, 128)
- `weekly_split`, `dated_goals`, `plan_start_date` — present
- `do NOT invent` / `never make up` / `never invent` — present
- `{training_profile}` at line 7 — unchanged

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. Changes are renderer/prompt-only.

T-21-08 (rigidity-drift): mitigated — renderer formats only label/modality/priority; test asserts no "attendance"/"completed"/"missed" in weekly_split rendering.
T-21-09 (DatetimeWithNanoseconds leak): mitigated — non_empty exclusion filter preserved, drops updated_at/bootstrapped_at/schema_version before rendering.
T-21-10 (anti-fabrication weakening): mitigated — "do NOT invent" discipline preserved and extended; Tier A/B discipline added; grep gates assert both survive.

## Self-Check: PASSED

- [x] `core/main.py` modified — "Coaching reference" at line 305
- [x] `prompts/smart_agent.md` modified — template/Tier A/B/update_plan language present
- [x] `tests/test_main_render_smart_system.py` modified — 21 tests pass
- [x] `tests/test_weekly_training_review.py` modified — 7 tests pass
- [x] Commits: 830ee8c (RED), ef8f560 (GREEN Task 1), 96b48f8 (Task 2), e2b5b45 (Task 3)
