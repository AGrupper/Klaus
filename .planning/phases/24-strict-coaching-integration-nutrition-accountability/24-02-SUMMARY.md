---
phase: 24-strict-coaching-integration-nutrition-accountability
plan: 02
subsystem: nutrition-accountability
tags: [nutr-01, nutr-02, nutr-03, pure-functions, tdd]
dependency_graph:
  requires: []
  provides:
    - MACRO_THRESHOLDS (module-level dict, proactive_alerts.py)
    - SLOT_SUPPLEMENTS (module-level dict, proactive_alerts.py)
    - _macro_gap_check pure function
    - _resolve_anchor_times pure function
    - _map_meals_to_slots pure function
    - _detect_slot_misses pure function
  affects:
    - Plan 04 (_gather_nutrition_data wiring)
tech_stack:
  added: []
  patterns:
    - Pure-function-no-I/O pattern (mirrors _slot_for, _detect_weather_conflicts style)
    - TDD RED/GREEN cycle with pytest
key_files:
  created: []
  modified:
    - core/proactive_alerts.py
    - tests/test_proactive_alerts.py
decisions:
  - "protein floor = 120g (80% of 150g blueprint target) — D-09 meaningful-gap threshold"
  - "carb floors: normal 250g, long_run 300g, deload/rest 200g — day-type-aware"
  - "anchor resolution: Garmin activity (priority 1) → calendar event (priority 2) → None on rest day (Pitfall 2 guard, D-10)"
  - "pre-bed slot #6 always evaluated; slots #2/#5 only when anchor resolved"
  - "SLOT_SUPPLEMENTS: plain dict at module level, consumed by Plan 04 at compose time"
metrics:
  duration: "~25 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 24 Plan 02: Nutrition Accountability Pure Functions Summary

## One-liner

Macro-gap detection (protein <120g/carb day-type floors), training-anchored fueling-slot miss detection, and supplement-rider mapping implemented as four pure helper functions — MACRO_THRESHOLDS and SLOT_SUPPLEMENTS module-level dicts added for Plan 04 wiring.

## What Was Built

### Task 1: Macro-gap check + thresholds (NUTR-01)

Added to `core/proactive_alerts.py`:

- **`MACRO_THRESHOLDS`** module-level dict encoding the "structurally meaningful shortfall" floors (D-09): protein floor 120g (80% of 150g blueprint target), carb floors by `day_type` (normal 250g, long_run 300g, deload/rest 200g). Sourced from `docs/hybrid_athlete_blueprint.md §6`.

- **`_macro_gap_check(totals, day_type, targets) -> list[dict]`** — pure function. Returns `{"topic_key", "description", "severity"}` dicts for protein-miss (< 120g) and carb-miss (< day-type floor). Marginal shortfalls (protein 145g on 150g target) produce no flag per D-09. Description always names the real number and the Tier-A blueprint target. Zero I/O.

### Task 2: Anchor resolution + slot mapping + miss detection + supplement riders (NUTR-02/03)

Added to `core/proactive_alerts.py`:

- **`SLOT_SUPPLEMENTS`** dict: `"post-am-run": "D3+K2/Omega-3"`, `"pm-post-lift": "Creatine"`, `"pre-bed": "Mg-Glycinate/Zinc/Copper"` (D-11 / NUTR-03).

- **`_resolve_anchor_times(today_iso, garmin_activities, calendar_events) -> (am, pm)`** — priority-1 Garmin activity type match, priority-2 calendar summary keyword match, returns None for both on rest day (Pitfall 2 guard, D-10 discretion). Accepts already-fetched data as args — no new I/O inside.

- **`_map_meals_to_slots(meals, am_anchor, pm_anchor) -> dict`** — buckets meals into all 6 named fueling slots using anchor-relative windows for slots #1–5 and fixed 12:00–14:30 / 21:00–23:59 for midday (#3) and pre-bed (#6). T-24-05 mitigation: malformed timestamps are silently skipped.

- **`_detect_slot_misses(meals, am_anchor, pm_anchor, today_date) -> list[str]`** — evaluates only the three HARD slots (#2 post-am-run, #5 pm-post-lift, #6 pre-bed). Critical Pitfall 2 guard: `am_anchor is not None` required before evaluating slot #2; `pm_anchor is not None` required before slot #5. Slot #6 is always evaluated (fixed window). T-24-07 mitigated.

### Tests added (tests/test_proactive_alerts.py)

27 new tests across `TestMacroGapCheck` and `TestSlotMappingAndMissDetection`:

- Protein below floor → flag; marginal shortfall → no flag (D-09 boundary test)
- Carbs: normal day 290g → no flag; long_run 290g → carb-miss:long-run-day flag; deload 190g → flag
- All macros met → empty list
- `MACRO_THRESHOLDS` and `SLOT_SUPPLEMENTS` dict existence and correct values
- Anchor resolution: Garmin running/trail_running, strength_training, calendar event fallback, rest day → None
- Slot miss: post-am-run miss detected, no miss when meal in window, pre-bed miss and no-miss
- Pitfall 2: rest day (am_anchor=None, pm_anchor=None) → "post-am-run" and "pm-post-lift" do NOT fire
- `_map_meals_to_slots`: meal bucketed into correct slot
- All functions callable without any GCP env vars (pure, no I/O)

## TDD Gate Compliance

RED commit: `31adbd0` (test(24-02): add failing tests)
GREEN commit: `dcc3050` (feat(24-02): implement pure helpers)

Both gate commits present. No REFACTOR step needed — code is clean as implemented.

## Deviations from Plan

None — plan executed exactly as written. All functions match the specified signatures and behavior.

The pre-existing test failure `test_benchmark_check_before_dedup_gate` (AttributeError on `memory.firestore_db` in Python 3.14 environment) is not caused by this plan — it fails identically on the main branch before any changes. Documented as out-of-scope per DEVIATION RULE scope boundary.

## Known Stubs

None. These are pure computational functions with no stub data paths. Plan 04 will wire them to real MealStore/Garmin data.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced in this plan. All new code is pure functions that accept already-fetched data as arguments. T-24-05 and T-24-07 mitigations from the threat model are implemented in `_map_meals_to_slots` and `_detect_slot_misses` respectively.

## Self-Check: PASSED

- FOUND: core/proactive_alerts.py (contains MACRO_THRESHOLDS, SLOT_SUPPLEMENTS, _macro_gap_check, _resolve_anchor_times, _map_meals_to_slots, _detect_slot_misses)
- FOUND: tests/test_proactive_alerts.py (27 new tests, all passing)
- FOUND commit 31adbd0 (RED test commit)
- FOUND commit dcc3050 (GREEN implementation commit)
- `python3 -m pytest tests/test_proactive_alerts.py -q -k "macro or slot or anchor or supplement"` → 27 passed, 0 failed
