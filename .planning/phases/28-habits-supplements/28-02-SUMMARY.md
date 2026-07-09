---
phase: 28-habits-supplements
plan: "02"
subsystem: api-routes
tags: [habits-api, auth-gate, backfill-gate, schedule-gate, tdd, time-06]
dependency_graph:
  requires: [HabitStore, compute_streak_and_grid, _is_scheduled, require_hub_session]
  provides: [/api/habits/*, /api/habits/summary, /api/habits/{id}/checkin, /api/habits/{id}/history]
  affects: [interfaces/web_server.py, tests/test_habits_api.py]
tech_stack:
  added: []
  patterns: [task-routes-CRUD, run_in_executor, _jsonsafe_doc, TDD-RED-GREEN, Pydantic-Literal-validation]
key_files:
  created:
    - tests/test_habits_api.py
  modified:
    - interfaces/web_server.py
decisions:
  - "_is_scheduled imported lazily inside GET /api/habits route — pure function, no Firestore, safe to call synchronously in the async handler"
  - "effective_from stripped from PATCH patch dict before calling store.update — store always uses today as revision date; gate validates client-provided value only"
  - "get_history called per habit in GET /api/habits for streak enrichment — O(N) Firestore calls, acceptable at personal scale of 10-20 items"
  - "/api/habits/summary declared before /api/habits/{habit_id} to avoid FastAPI route shadowing"
requirements-completed: [HABIT-01, HABIT-02, TIME-06]
metrics:
  duration: "~25 minutes"
  completed: "2026-06-30"
  tasks_completed: 2
  files_changed: 2
---

# Phase 28 Plan 02: /api/habits/* Routes Summary

**One-liner:** Nine FastAPI routes under `/api/habits/*` gated by `require_hub_session`, enforcing the D-11 backfill-floor (today|yesterday only) and D-19 forward-only schedule gate, with `GET /api/habits` enriching each item with `scheduled_today`/`done_today`/`dose_taken`/`streak` for the TIME-06 timeline band.

## Tasks Completed

| # | Task | Commit | Status |
|---|------|--------|--------|
| 1 | Wave-0 API test scaffold (RED) | 2e377a5 | Done |
| 2 | /api/habits/* routes + Pydantic validation + backfill & schedule gates (GREEN) | af53d92 | Done |

## What Was Built

### `tests/test_habits_api.py` (8 tests)

TDD RED scaffold pinning the three Tampering mitigations and the TIME-06 API contract:

- **test_habits_routes_require_session** — GET/POST /api/habits + POST checkin without session cookie → 401 (T-28-AC). Exercises the `CRON_DEV_BYPASS=false` path so the real `require_hub_session` runs.
- **TestCheckinEndpoint** (4 tests) — done=True/False for today → 200; yesterday → 200 (backfill window D-11); day-before-yesterday → 400 with error detail (T-28-backfill gate).
- **test_list_scheduled_today** — GET /api/habits returns `scheduled_today=True` for a daily habit; `done_today` is False before a completion and True after (TIME-06 API contract).
- **test_patch_schedule_rejects_past_effective_from** — PATCH with `effective_from="2020-01-01"` → 400 (D-19 / T-28-schedule gate).
- **test_hard_delete_requires_completing** — hard-delete on an active habit → 409 (D-20 gate).

Mock strategy: Firestore mock installed at module level (mirrors `test_task_store.py`); heavy web_server deps stubbed via `patch.dict(sys.modules)`; `require_hub_session` overridden via `app.dependency_overrides`; `HabitStore` patched per-test via `patch("memory.firestore_db.HabitStore", return_value=instance)`.

### `interfaces/web_server.py` additions (411 lines)

**Pydantic models:**
- `CreateHabitInput` — name (1..500), type Literal["habit","supplement"], dose (≤200), slot Literal["Morning","Noon","Evening","Bedtime"], days ("daily"|list[int])
- `EditHabitInput` — all optional; same constraints plus optional `effective_from` (date pattern) for the schedule gate
- `CheckinInput` — date (YYYY-MM-DD pattern), done bool, dose_taken (≤200)

**Routes (all behind `Depends(require_hub_session)`, all Firestore calls via `run_in_executor`):**

| Route | Purpose | Gate |
|-------|---------|------|
| `GET /api/habits/summary` | pending_today + streak_leaders for GlanceRail | auth |
| `GET /api/habits` | list_active enriched with scheduled_today/done_today/dose_taken/streak | auth |
| `POST /api/habits` | create habit/supplement | auth + Pydantic |
| `PATCH /api/habits/{id}` | update; schedule revision | auth + D-19 gate (past effective_from → 400) |
| `POST /api/habits/{id}/checkin` | toggle completion | auth + D-11 gate (>yesterday → 400) |
| `GET /api/habits/{id}/history` | 365-day four-state grid + streak | auth |
| `POST /api/habits/{id}/soft-delete` | set status=completing | auth |
| `POST /api/habits/{id}/restore` | set status=active | auth |
| `POST /api/habits/{id}/hard-delete` | delete + completions | auth + D-20 gate (not completing → 409) |

**TIME-06 enrichment in GET /api/habits:**
Each habit in the response carries `scheduled_today` (computed via `_is_scheduled` — pure function, no Firestore), `done_today` + `dose_taken` (from `get_completions_for_date`), and `streak` (from `get_history` per habit). This allows `HabitsBand` to render one-tap items without extra calls.

**Route declaration order:** `/api/habits/summary` is registered before the parametric `/api/habits/{habit_id}` to prevent FastAPI route shadowing (same invariant as `/api/tasks/summary`).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The API routes delegate fully to `HabitStore` and return real Firestore data. No placeholder values flow to UI rendering.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. All nine routes gate on `require_hub_session` (T-28-AC). Backfill and schedule gates are enforced (T-28-backfill, T-28-schedule). OIDC `/cron|/internal|/trigger` routes are untouched (HUB-04 verified via grep).

## TDD Gate Compliance

- RED gate: commit `2e377a5` — `test(28-02): add failing tests for /api/habits/* routes (RED)` — 8 tests fail on missing routes, not import errors.
- GREEN gate: commit `af53d92` — `feat(28-02): add /api/habits/* routes behind require_hub_session` — 8/8 tests pass.

## Self-Check: PASSED

- `tests/test_habits_api.py` exists: YES (489 lines, 8 tests, all PASS)
- `test_checkin_rejects_day_before_yesterday` exists verbatim: YES
- `test_list_scheduled_today` exists verbatim: YES
- `test_patch_schedule_rejects_past_effective_from` exists verbatim: YES
- Commit `2e377a5` exists: YES (RED)
- Commit `af53d92` exists: YES (GREEN)
- `/api/habits/summary` declared before `/api/habits/{habit_id}` in file: YES (line 2214 vs 2339)
- `grep -c "Depends(require_hub_session)" interfaces/web_server.py` → 27 (increased by 9 new habit routes)
- `pytest tests/test_hub_auth.py -q` → 4 passed
- `pytest tests/test_habit_store.py -q` → 32 passed (Plan 01 store unmodified)
- No `dangerouslySetInnerHTML` in web_server.py: CONFIRMED
- No OIDC route signatures modified: CONFIRMED
- Concurrent-session files (core/tools.py, mcp_tools/calendar_tool.py, prompts/smart_agent.md, tests/test_calendar_tool.py, tests/test_tools.py) NOT staged or committed: CONFIRMED
