---
phase: 26-hub-shell
plan: "04"
subsystem: api
tags: [api, today, aggregator, calendar, garmin, weather, meals, training, routes, firestore]
dependency_graph:
  requires: ["26-02", "26-03"]
  provides: ["GET /api/today aggregator", "per-source helpers", "test_api_today.py real assertions"]
  affects: ["interfaces/web_server.py"]
tech_stack:
  added: []
  patterns:
    - asyncio.gather + run_in_executor for sync tools in async route (Pitfall 2)
    - _jsonsafe_doc wrapping on all Firestore-derived data before JSONResponse (Pitfall 4)
    - module-level TTL cache dict (_routes_cache, 30-min) for Routes API quota protection
    - require_hub_session Depends() — imported at module level for route-definition time
    - per-helper try/except fault isolation (one failing source never 500s the whole timeline)
key_files:
  created: []
  modified:
    - interfaces/web_server.py
    - tests/test_api_today.py
decisions:
  - "require_hub_session imported at module level (not lazy) so Depends() resolves at route-definition time"
  - "_today_coach_note gates on daily_note_date == today_iso (D-06 staleness guard)"
  - "_routes_cache keyed on (event_id, start_iso) with 30-min TTL (T-26-04-04 quota protection)"
  - "Meals emit slot_label + slot_time identifier only — no eaten_at/eating_time fields (CLAUDE.md §6 / TIME-03)"
  - "Training block uses morning_briefing's plan_start_date=2026-06-21 anchor for week_num derivation"
metrics:
  duration_minutes: 6
  completed_date: "2026-06-15"
  tasks_completed: 3
  files_modified: 2
---

# Phase 26 Plan 04: /api/today Aggregator Summary

GET /api/today aggregator with 8 fault-isolated per-source helpers, asyncio.gather + run_in_executor for all sync tools, _jsonsafe_doc on all Firestore data, slot-time caveat enforced, and 4 real test assertions replacing Wave 0 skips.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Per-source helpers (calendar, garmin, weather, meals, training, coach_note, routes, nutrition_totals) | e931be0 | interfaces/web_server.py |
| 2 | GET /api/today route — gather, _jsonsafe_doc, behind require_hub_session | e931be0 | interfaces/web_server.py |
| 3 | Flip tests/test_api_today.py skips to real assertions | 6c68a16 | tests/test_api_today.py |

## What Was Built

### Per-source helpers (Task 1)

Eight module-level helper functions added to `interfaces/web_server.py`:

- `_today_calendar(today_iso)` — fetches today's events via GoogleCalendarManager, splits into `all_day` (pinned) + `timed` (chronological). Detects all-day by absence of 'T' in start string (length-10 date-only). TIME-01.
- `_today_garmin()` — calls `fetch_garmin_today()`, returns dict with sleep/HRV/body_battery/resting_hr or `None` when Garmin not yet synced (D-06). TIME-02 stats.
- `_today_weather()` — calls `fetch_weather("Tel Aviv")`, assembles one-line summary string. TIME-02 weather.
- `_today_meals(today_iso)` — calls `MealStore.get_day()`, maps canonical slot timestamps (08:00/12:00/20:00) to labels (Breakfast/Lunch/Dinner). Emits `slot_label` + `slot_time` + `macros` only — NO `eaten_at`/`eating_time` field (TIME-03 / CLAUDE.md §6 invariant).
- `_today_training(today_iso)` — calls `BlockStore.get_current()` + `UserProfileStore.load()` to derive `"Week N of 16 — {split_name}"` using the 2026-06-21 plan_start_date anchor, mirroring `core/morning_briefing.py` lines 399–420. TIME-04.
- `_today_coach_note(today_iso)` — reads `SelfStateStore.get()` and returns `daily_note` ONLY when `daily_note_date == today_iso`. Returns `None` otherwise (D-06 staleness gate). TIME-07.
- `_today_routes(calendar, today_iso)` — iterates timed events with a `location`, calls `routes_tool.get_travel_time()`, attaches `leave_by_minutes_before` + `routes_summary`. Module-level `_routes_cache` dict with 30-min TTL keyed on `(event_id, start_iso)` prevents quota exhaustion on D-05 refresh-on-focus (T-26-04-04). TIME-05.
- `_today_nutrition_totals(today_iso)` — calls `MealStore.get_day_aggregate()`, extracts `{kcal, protein_g, carbs_g, fat_g, fiber_g}` from the server-computed totals. Returns `{}` when no meals logged. TIME-08.

All helpers wrapped in `try/except` returning a safe empty/None default — one failing source never 500s the whole timeline.

### GET /api/today route (Task 2)

Route registered at line 1350, before the SPAStaticFiles mount at line 1451 (Pitfall 1).

- Uses `Depends(require_hub_session)` — imported at module level so FastAPI's dependency system resolves it at route-definition time.
- Phase 1: `asyncio.gather` with 6 independent sources via `loop.run_in_executor` (Pitfall 2 — no sync calls in the async body).
- Phase 2: `_today_routes` runs sequentially after calendar (depends on calendar output).
- Phase 3: `_today_coach_note` lightweight cached read.
- Response assembled and wrapped in `_jsonsafe_doc(...)` before `JSONResponse` (Pitfall 4).

### Test assertions (Task 3)

All 4 Wave 0 skips removed and replaced with real assertions:

- `test_today_returns_expected_keys` — monkeypatches 8 helpers, GETs `/api/today`, asserts response has `calendar`, `garmin`, `weather`, `meals`, `training`, `coach_note`, `nutrition_totals` keys plus `all_day`/`timed` sub-structure.
- `test_no_datetimewithnanoseconds_leak` — injects `_FakeDatetimeWithNanoseconds` (duck-type with `isoformat()`) into helper returns, asserts `json.loads(response.text)` succeeds and `_updated_at` is a string, not an object (Pitfall 4 / T-26-04-05).
- `test_meal_slot_time_not_eating_time` — provides realistic 3-meal fixture, asserts every meal has `slot_label`, asserts NO `eaten_at`/`eating_time` key in any meal dict or nested macros dict (TIME-03 / CLAUDE.md §6 invariant / T-26-04-03).
- `test_unauthenticated_returns_401` — sets `CRON_DEV_BYPASS=false`, no cookie, asserts 401 (T-26-04-01 / HUB-01).

pytest result: 4/4 passed, 0 skipped. Hub suite (`-k "hub or today or web_server"`): 72 passed, 4 pre-existing skips.

## Deviations from Plan

None — plan executed exactly as written.

The only minor implementation detail that differs from the plan's code skeleton is that `require_hub_session` is imported at module level (not lazy-imported inside the route handler). This is required because FastAPI evaluates `Depends(...)` at route-registration time, not at request time. A lazy import inside the handler would cause a `NameError` at startup. This is consistent with the existing codebase pattern (e.g., `core.task_dispatch.enqueue_update` is imported at module level).

## Threat Flags

No new network endpoints or trust-boundary changes beyond what the threat model anticipated. All 5 STRIDE threats (T-26-04-01..05) are mitigated:

| Flag | File | Description |
|------|------|-------------|
| (none new) | — | All surface introduced is covered by plan's threat model |

## Known Stubs

None. All 8 helpers are wired to real data sources. The route returns real data on a production deploy (Garmin returns `None` before sync as designed; coach_note returns `None` before morning briefing as designed — these are intentional D-06 placeholders, not stubs).

## Self-Check

### Created files exist:
- `tests/test_api_today.py` — FOUND (modified from stub; 252 net insertions)
- `interfaces/web_server.py` — FOUND (modified; 418 net insertions)

### Commits exist:
- e931be0 — FOUND (Tasks 1+2)
- 6c68a16 — FOUND (Task 3)
