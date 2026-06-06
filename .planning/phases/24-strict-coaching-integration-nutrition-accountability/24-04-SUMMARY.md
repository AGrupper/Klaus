---
phase: 24
plan: "04"
subsystem: proactive-alerts
tags:
  - coaching
  - nutrition-accountability
  - dedup-gate
  - prompt-engineering
  - tdd
dependency_graph:
  requires:
    - "24-01"  # MACRO_THRESHOLDS, SLOT_SUPPLEMENTS, pure helpers
    - "24-02"  # _macro_gap_check, _detect_slot_misses
    - "24-03"  # CoachingTopicStore (Wave 1 merged)
  provides:
    - "_gather_nutrition_data helper wired into run_proactive_alerts"
    - "Cross-cron coaching dedup gate (COACH-05)"
    - "COACH-03 strict-pushback prompt block"
    - "COACH-04 recovery single-rec prompt block"
    - "NUTR-01/02/03 nutrition accountability prompt blocks"
    - "Reactive counterpart in smart_agent.md"
  affects:
    - core/proactive_alerts.py
    - tests/test_proactive_alerts.py
    - prompts/proactive_alert.md
    - prompts/smart_agent.md
tech_stack:
  added: []
  patterns:
    - "Best-effort gather with try/except per data source"
    - "Write-after-send discipline (CoachingTopicStore.add_topic post send_and_inject)"
    - "Fail-open on gate failure (all topics fire if store unavailable)"
    - "sys.modules patch pattern for Python 3.14 compatibility"
    - "Jerusalem-time date key for CoachingTopicStore"
key_files:
  created: []
  modified:
    - core/proactive_alerts.py
    - tests/test_proactive_alerts.py
    - prompts/proactive_alert.md
    - prompts/smart_agent.md
decisions:
  - "_gather_nutrition_data takes garmin_activities as parameter to avoid a second Garmin call; activities already fetched for ACWR/anchor resolution"
  - "calendar_events=[] for anchor resolution in nutrition gather path (cron fetches tomorrow calendar, not today)"
  - "_cts initialized to None; None-guard on post-send write skips write if gate fails, avoiding try/except nesting"
  - "_collect_detected_topics is a pure function (no I/O) derived from alerts_context keys"
  - "sys.modules patching with explicit save/restore replaces unittest.mock.patch for Python 3.14 compatibility"
metrics:
  duration: "~45 minutes"
  completed: "2026-06-06"
  tasks: 2
  files_modified: 4
  tests_added: 20
  tests_passing: 62
  tests_pre_existing_failures: 2
---

# Phase 24 Plan 04: Nutrition Gather + Dedup Gate Wiring + Prompt Behavior Summary

**One-liner:** Wire `_gather_nutrition_data` into the 21:30 cron with cross-cron coaching dedup gate, and add four prompt behavior blocks (COACH-03, COACH-04, NUTR-01/02/03, COACH-05) to `proactive_alert.md` and their reactive counterpart to `smart_agent.md`.

## Tasks Completed

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | _gather_nutrition_data + dedup gate wiring | c9e7f74 (RED), 127bf62 (GREEN) | core/proactive_alerts.py, tests/test_proactive_alerts.py |
| 2 | Prompt behavior blocks | acdd56e (RED), 1046468 (GREEN) | prompts/proactive_alert.md, prompts/smart_agent.md, tests/test_proactive_alerts.py |

## What Was Built

### Task 1: _gather_nutrition_data + Cross-Cron Dedup Gate

**`_gather_nutrition_data(today_iso, garmin_activities=None) -> dict`**

Best-effort gather function returning `{meals, macro_totals, macro_gaps, slot_misses, am_anchor, pm_anchor}`. Each data source wrapped in try/except; failures degrade gracefully and return empty structures. Derives day_type from garmin activities list (looks for `"running"` or `"cycling"` in activity types for long-run detection). Uses `MealStore.get_day()`, `UserProfileStore`, `_macro_gap_check`, `_map_meals_to_slots`, `_detect_slot_misses`.

**`_collect_detected_topics(alerts_context) -> list[str]`**

Pure function with no I/O. Scans `alerts_context` for topic keys:
- `nutrition.macro_gaps` items: uses `gap["topic_key"]`
- `nutrition.slot_misses` items: formatted as `fueling-miss:{slot}`
- `recovery_concern` key: formatted as `recovery-conflict:{level}`

**Dedup gate wiring in `run_proactive_alerts`:**

1. `garmin_activities = fetch_garmin_activities(days=1)` — separate call from `fetch_garmin_today()` (different endpoint, different data)
2. `nutrition_data = _gather_nutrition_data(today_iso, garmin_activities=_garmin_activities)`
3. `alerts_context["nutrition"] = nutrition_data`
4. `CoachingTopicStore` gate: `topics_today()` → filter `_collect_detected_topics()` against already-raised → wire `coaching_topics_new` and `coaching_topics_already_raised` into alerts_context
5. Post-send: `_cts.add_topic(_today_il, topic)` for each topic in `_topics_to_record` — ONLY after `send_and_inject` succeeds

**Key invariants:**
- `_cts = None` if gate fails → None-guard on post-send write skips write entirely (fail-open)
- Jerusalem-time date key: `datetime.now(_TZ).date().isoformat()`
- Write-after-send discipline (D-10 analog for coaching topics)

### Task 2: Prompt Behavior Blocks

**`prompts/proactive_alert.md` — four new sections:**

1. **Strict Skip / Off-Plan Pushback (COACH-03)**: Named session + concrete deficit in measured units + directional consequence tied to block goal. No softening, no hedging, no dated projection. Escalate tone on pattern (2nd/3rd miss). Example: "2nd threshold run skipped this week — ~12km off your Week-3 aerobic target. Miss the volume now and the Oct half-marathon pace slips, Sir."

2. **Recovery-vs-Plan Conflict (COACH-04)**: Cite biometric with literal number + state plan conflict + exactly ONE ranked recommendation + "your call, Sir". Never a menu, never dictate. Example: "HRV 58, 71% of baseline, against a top-set bench day. I'd swap to technique work at 70% and push the heavy triple to Thursday — but your call, Sir."

3. **Nutrition Accountability (NUTR-01/02/03)**: Structural shortfalls only. Supplement riders on hard slot misses: post-am-run → "D3+K2/Omega-3 gone with it", pm-post-lift → "Creatine window missed", pre-bed → "Mg-Glycinate/Zinc/Copper window missed". Pattern critique (NUTR-01 × COACH-07) pattern-triggered only, at most once per day.

4. **Cross-Cron Dedup Semantics (COACH-05)**: `coaching_topics_already_raised` not repeated. Escalation allowed if materially worsened with explicit framing ("Still no post-run reload three hours later…").

**`prompts/smart_agent.md` — two new sections:**

1. **Reactive strict-pushback + recovery conflict format (COACH-03/04)**: Same format as 21:30 cron — named session, concrete deficit, directional consequence, no softening, no dated projection, one ranked rec, "your call, Sir".

2. **Reactive chat and cron dedup (COACH-05 / D-03)**: Reactive chat always answers fully; never suppressed by cron topics; does not burn topic for later crons.

## Test Coverage

Added 20 new tests across three test classes:

- `TestGatherNutritionData` (5 tests): function existence, returns dict, no-meal day no crash (Pitfall 7: `get_day()` returns `[]` not `None`), required keys present, store failure best-effort
- `TestDedupGateWiring` (5 tests): already-raised topic excluded from new_topics, add_topic not called when send fails, add_topic called after successful send, dedup gate failure fail-open, Jerusalem time used for date key
- `TestPromptContent` (10 tests): structural assertions for proactive_alert.md (COACH-03 markers: no softening, no dated projection, named session; COACH-04 markers: one ranked rec, your call sir; NUTR-01/02/03 markers: supplement riders; COACH-05 markers: dedup semantics) and smart_agent.md (reactive never suppressed, strict pushback format)

Final state: **62 passed, 2 pre-existing failures** (both `test_benchmark_check_before_dedup_gate` and `test_benchmark_only_night_still_sends` — same Python 3.14 `pkgutil.resolve_name` failure as before Plan 04, unaffected).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Python 3.14 sys.modules patch incompatibility**
- **Found during:** Task 1 RED phase
- **Issue:** `unittest.mock.patch("memory.firestore_db.MealStore")` fails in Python 3.14 because `pkgutil.resolve_name` calls `getattr(memory, "firestore_db")` which raises `AttributeError: module 'memory' has no attribute 'firestore_db'` when the submodule isn't set as an attribute on the parent package.
- **Fix:** Created `_make_firestore_db_mock()` helper that builds a `types.ModuleType("memory.firestore_db")` fake module and installs it directly via `sys.modules["memory.firestore_db"]` AND sets `_memory_pkg.firestore_db = fake_db` attribute. `_run_cron()` helper manages full lifecycle with proper teardown (restore original or delete new key).
- **Files modified:** tests/test_proactive_alerts.py
- **Commits:** c9e7f74 (RED), 127bf62 (GREEN)

**2. [Rule 2 - Missing functionality] `calendar_events=[]` for nutrition anchor resolution**
- **Found during:** Task 1 implementation
- **Issue:** `_gather_nutrition_data` calls `_resolve_anchor_times` but the proactive alerts cron fetches tomorrow's calendar events, not today's. No today-calendar available in the nutrition gather path.
- **Fix:** Pass `calendar_events=[]` explicitly — `_resolve_anchor_times` handles empty list gracefully by falling back to hardcoded defaults.
- **Files modified:** core/proactive_alerts.py
- **Commits:** 127bf62 (GREEN)

## Known Stubs

None — all data paths wired to live stores. Nutrition data returns empty structures on gather failure (best-effort), not placeholder text.

## Threat Flags

No new network endpoints or auth paths introduced. `CoachingTopicStore` reads/writes to existing `coaching_topics` Firestore collection (Wave 1 scope). No new trust boundaries.

## Self-Check: PASSED

- [x] core/proactive_alerts.py modified: `_gather_nutrition_data` at line 503, dedup gate wiring at lines 797-838
- [x] tests/test_proactive_alerts.py modified: 3 new test classes, 20 new tests
- [x] prompts/proactive_alert.md modified: 4 new sections (COACH-03/04, NUTR-01/02/03, COACH-05)
- [x] prompts/smart_agent.md modified: 2 new sections (reactive pushback format, reactive dedup rule)
- [x] Commits: c9e7f74 (RED T1), 127bf62 (GREEN T1), acdd56e (RED T2), 1046468 (GREEN T2)
- [x] TDD gate compliance: RED commits before GREEN commits confirmed in git log
- [x] 62 tests pass, 2 pre-existing failures unchanged
