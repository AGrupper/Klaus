# Hevy Strength Integration

Klaus syncs Amit's weight-training from **Hevy** so he can see — and reason over — full
per-set progression (every exercise, set, rep, weight, RPE), not just session-level
metadata. This document covers setup, the data model, and how the data flows into coaching.

## Why Hevy (and not Strong)

Strong has **no public API** — it only exports a manual CSV. Hevy exposes a real developer
API with full workout detail, so Klaus can sync automatically. Apple Health is a dead end
for this: Strong/Hevy only write workout *summaries* (type + duration + calories) to
HealthKit, never per-set reps/weight.

## Prerequisite: Hevy Pro + API key

The Hevy API is **Pro-only**.

1. Subscribe to Hevy Pro.
2. Generate an API key at <https://hevy.com/settings?developer> (a UUID).
3. Store it as the `HEVY_API_KEY` secret (`klaus-hevy-api-key` in Secret Manager) and bind
   it to Cloud Run — see `docs/DEPLOYMENT.md` §20a.

The key is sent as the `api-key` request header. There are **no webhooks**, so sync is a
daily pull.

## How sync works

`POST /cron/strength-sync` (Cloud Scheduler job `klaus-strength-sync`, `0 5 * * *`
Asia/Jerusalem) runs `core/strength_ingest.py:run_one_batch()`:

- **First run (backfill):** paginates `GET /v1/workouts` newest-first, upserting every
  workout. Bounded per tick (`STRENGTH_INGEST_MAX_PAGES`, default 5; time budget 45s), so a
  large history drains over multiple ticks. Re-invoke until the response shows `done: true`.
- **Steady state (delta):** `GET /v1/workouts/events?since=<cursor>` applies `updated`
  (upsert) and `deleted` (delete) events. The `last_synced_at` cursor only advances on a
  full drain, so nothing is skipped; upserts are idempotent (keyed on Hevy `workout_id`).

State lives in Firestore `strength_ingest/state`. The path is pull-only — no orchestrator,
no LLM, no Telegram.

Local dry-run:

```bash
HEVY_API_KEY=... GCP_PROJECT_ID=klaus-agent python -m core.strength_ingest
```

## Data model

`memory/firestore_db.py::StrengthSessionStore` — collection `strength_sessions`, doc id =
Hevy `workout_id`. Each doc (normalized by `mcp_tools/hevy_tool.py::normalize_workout`):

```
workout_id, title, description, start_time, end_time,
date            # Asia/Jerusalem calendar date from start_time
duration_min,
total_volume_kg,
exercises: [
  { name, template_id, notes,
    sets: [ {index, type, weight_kg, reps, rpe, distance_meters, duration_seconds} ],
    set_count,                  # working sets (warmup excluded)
    top_set: {weight_kg, reps}, # heaviest working set
    est_1rm,                    # max Epley estimate across working sets: w*(1+reps/30)
    volume_kg },                # Σ weight×reps over working sets
]
```

Derived metrics exclude warmup sets and bodyweight/cardio sets (no weight×reps).

## How Klaus uses it

The goal is **unrestricted, cross-domain coaching** — Klaus sees everything and reasons for
himself, rather than emitting a fixed template.

- `get_strength_progress(exercise=None, days=30, detail="full")` — brain-direct tool.
  With `exercise`, returns that lift's per-session progression (top_set / est_1rm / volume)
  for trend and stall detection; without it, recent full sessions.
- `get_training_context(days=14)` — brain-direct tool that assembles the FULL picture in one
  call: strength + session log + running/cardio + ACWR + Garmin status + nutrition per day +
  recovery (HRV/RHR/sleep). Lets Klaus correlate across domains (e.g. a bench stall lining up
  with low protein and poor sleep).
- **Weekly review** (`core/weekly_training_review.py`) gathers `strength_sessions` (this week
  + prior week) and the prompt (`prompts/weekly_training_review.md`) is framed as an open
  analytical brief — find the non-obvious thing, vary focus week to week, never fabricate.

## Tests

`tests/test_hevy_tool.py`, `tests/test_strength_session_store.py`,
`tests/test_strength_ingest.py`, `tests/test_strength_sync_endpoint.py`,
`tests/test_tool_registration_strength.py`, and the strength cases in
`tests/test_weekly_training_review.py`.
