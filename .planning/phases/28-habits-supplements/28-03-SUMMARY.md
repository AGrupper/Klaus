---
phase: 28-habits-supplements
plan: "03"
subsystem: backend-integration
tags: [habit-adherence, autonomous-tick, proactive-alerts, tdd, coaching, dedup]
dependency_graph:
  requires: [HabitStore, CoachingTopicStore, compute_streak_and_grid]
  provides: [get_habit_adherence, _gather_habit_adherence, _get_supplement_checkoffs]
  affects:
    - core/tools.py
    - core/autonomous.py
    - core/proactive_alerts.py
    - prompts/proactive_alert.md
tech_stack:
  added: []
  patterns:
    - TDD-RED-GREEN (two tasks, two cycles)
    - sentinel-on-error (_gather_habit_adherence returns [], _get_supplement_checkoffs returns {})
    - CoachingTopicStore dedup (per-item-per-day topic key habit-nudge:{id}:{date})
    - _is_empty_signals extension (habit_pending as tick trigger)
decisions:
  - "habit_pending is a Layer-0 gather key (D-15): a non-empty list wakes tick-brain at $0 cost"
  - "Per-item dedup topic key is the plain string habit-nudge:{habit_id}:{today_iso} (D-17, Pitfall 4)"
  - "SLOT_SUPPLEMENTS kept unchanged as fallback; _get_supplement_checkoffs() overlays real data (D-01)"
  - "Bedtime/pre-bed supplements are NOT in the 7-21 tick window — 21:30 alert covers them (D-18)"
  - "_gather_habit_adherence and _get_supplement_checkoffs both return empty sentinels on exception (T-28-gather-fail)"
key_files:
  created: []
  modified:
    - core/tools.py
    - core/autonomous.py
    - core/proactive_alerts.py
    - prompts/proactive_alert.md
    - tests/test_autonomous.py
    - tests/test_tools.py
    - tests/test_proactive_alerts.py
metrics:
  duration: "~45 minutes"
  completed: "2026-06-30"
  tasks_completed: 2
  files_changed: 7
---

# Phase 28 Plan 03: Backend Adherence Awareness Summary

**One-liner:** Native `get_habit_adherence` tool + autonomous Layer-0 habit_pending gather (with per-item CoachingTopicStore dedup) + `_get_supplement_checkoffs` rewiring SLOT_SUPPLEMENTS to real HabitStore check-off data.

## Tasks Completed

| # | Task | Commit | Status |
|---|------|--------|--------|
| 1 RED | Failing tests: habit tool + autonomous gather | c6004de | Done |
| 1 GREEN | core/tools.py + core/autonomous.py implementation | 16a3b2c | Done |
| 2 RED | Failing tests: supplement checkoffs rewire | cbb0dec | Done |
| 2 GREEN | core/proactive_alerts.py + prompts/proactive_alert.md | ef2bda8 | Done |

## What Was Built

### `core/tools.py` additions

**`_get_habit_store()`** — singleton accessor (mirrors `_get_task_store`): reads `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` from env.

**`_habit_today_iso()`** — returns today's date in Asia/Jerusalem as YYYY-MM-DD (mirrors `_task_today_iso`).

**`_handle_get_habit_adherence(slot, type)`** — handler: calls `HabitStore.get_pending_today(today_iso)`, applies optional `slot`/`type` filters, returns `json.dumps(pending)`.

**`get_habit_adherence` tool schema** — registered in `TOOL_SCHEMAS` with optional `slot` enum (Morning/Noon/Evening/Bedtime) and `type` enum (habit/supplement). Registered in `_HANDLERS`.

### `core/autonomous.py` additions

**`_gather_habit_adherence(now, project_id, database)`** — Layer-0 gather function:
- Calls `HabitStore.get_pending_today(today_iso)` to get all pending items
- Filters via `CoachingTopicStore.has_topic(today_iso, f"habit-nudge:{habit_id}:{today_iso}")` to exclude already-nudged items (D-17)
- Returns `[]` on any exception (sentinel — HabitStore failure must never break the tick, T-28-gather-fail)

**jobs dict extension** — `"habit_pending": lambda: _gather_habit_adherence(now, project_id, database)` added to the parallel gather fan-out.

**`_is_empty_signals` extension** — added `if situation.get("habit_pending"): return False` so a non-empty pending list wakes tick-brain at $0 cost (D-15 per-slot salience).

**`_build_triage_prompt` extension** — `habit_pending` added to the snap dict so tick-brain sees items + streaks (D-16).

**`_compose_layer2` extension** — `habit_pending` added to snap_summary for parity, so the brain's compose layer sees the same context (D-16).

### `core/proactive_alerts.py` additions

**`_HABIT_SLOT_TO_FUELING`** — slot mapping dict: Morning→post-am-run, Noon→pm-post-lift, Evening→pm-post-lift, Bedtime→pre-bed (D-02).

**`_get_supplement_checkoffs(today_iso)`** — reads `HabitStore.list_active()` filtered to supplements, reads `get_completions_for_date(today_iso)`, builds `{fueling_slot: {"name", "done", "habit_id"}}`. Returns `{}` on any exception (non-fatal — prompt degrades to hardcoded SLOT_SUPPLEMENTS riders).

**`run_proactive_alerts` extension** — calls `_get_supplement_checkoffs(today_iso)` and, when non-empty, sets `alerts_context["supplement_checkoffs"]` (D-01).

**SLOT_SUPPLEMENTS kept unchanged** — backward-compat fallback when HabitStore has no supplements.

### `prompts/proactive_alert.md` update

The fueling-slot accountability section now instructs the LLM to:
- When `supplement_checkoffs` is present: use the real supplement name from HabitStore (`supplement_checkoffs[slot].name`) for each hard-slot miss, and suppress the rider if `done=True`.
- When `supplement_checkoffs` is absent/empty: fall back to the existing hardcoded names (D3+K2/Omega-3, Creatine, Mg-Glycinate/Zinc/Copper).

### Test Extensions (append-only — no pre-existing test removed)

**`tests/test_autonomous.py`** — 52 → 62 tests (+10):
- `TestPhase28HabitGather` (10 tests): tool registration, filter behavior, sentinel, D-15 trigger, D-17 dedup, triage/compose include habit_pending.

**`tests/test_tools.py`** — 61 → 67 tests (+6):
- `TestNativeHabitTools` (6 tests): schema registration, optional properties, handler returns JSON, slot filter, type filter.

**`tests/test_proactive_alerts.py`** — 72 → 81 tests (+9):
- `TestSupplementCheckoffs` (9 tests): mapping exists, function exists, slot mapping, completion reflection, empty fallback, error swallowing, Bedtime→pre-bed, Noon→pm-post-lift, constant preserved.

## Deviations from Plan

None - plan executed exactly as written. All patterns followed from 28-PATTERNS.md. All threat mitigations applied (sentinel returns, plain-string topic keys, write-after-send discipline unchanged).

## Known Stubs

None. The implementation reads real HabitStore data (seeded by the user in the Hub). When the store is empty, all paths degrade gracefully to existing hardcoded fallbacks.

## Threat Flags

None. No new network endpoints or auth paths introduced. All reads go through the existing HabitStore + CoachingTopicStore which are already behind GCP auth. The `_get_supplement_checkoffs` function uses `os.environ["GCP_PROJECT_ID"]` (raises KeyError if unset) which matches the existing proactive_alerts.py pattern for all other store calls.

## Self-Check: PASSED

- `grep -q "get_habit_adherence" core/tools.py` — FOUND (schema + handler + HANDLERS)
- `grep -q "_gather_habit_adherence" core/autonomous.py` — FOUND
- `grep -q '"habit_pending"' core/autonomous.py` — FOUND (jobs dict + empty check + triage + compose)
- `grep -q "_get_supplement_checkoffs" core/proactive_alerts.py` — FOUND
- `python -c "import core.autonomous, core.tools, core.proactive_alerts"` — imports cleanly
- `pytest tests/test_autonomous.py -q` — 62 passed (up from 52)
- `pytest tests/test_tools.py -q` — 67 passed (up from 61)
- `pytest tests/test_proactive_alerts.py -q` — 81 passed (up from 72)
- Commits: c6004de (RED 1), 16a3b2c (GREEN 1), cbb0dec (RED 2), ef2bda8 (GREEN 2)
