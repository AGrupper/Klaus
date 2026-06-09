---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: — Specific Training & Nutrition Coaching
status: Awaiting next milestone
stopped_at: Phase 25 Plan 03 complete — all tasks executed, SUMMARY.md created
last_updated: "2026-06-09T20:30:00.000Z"
last_activity: 2026-06-09 — nutrition: accurate+training-aware coaching, HealthKit dedup fix, centralized Garmin-synced bodyweight (rev klaus-agent-00102-9nk)
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 20
  completed_plans: 20
  percent: 100
---

# State — Klaus

## Current Position

Phase: Milestone v4.0 complete; post-v4.0 increments shipped (latest: per-run Garmin detail)
Plan: —
Status: Awaiting next milestone
Last activity: 2026-06-09 — per-run Garmin run-detail capture + coaching calibration fix shipped

## Post-v4.0 Increments (out-of-band, not a GSD milestone)

- **Nutrition: accurate, training-aware coaching + centralized bodyweight** (2026-06-09, three increments):
  1. *Accurate + prescriptive chat coaching* (rev `klaus-agent-00100-dnh`): `fetch_recent_meals` made
     brain-direct and now returns **server-computed** `totals_by_day`/`window_totals` (via
     `get_day_aggregate`) — LLM column-summing across a worker hop was producing wrong, drifting
     numbers. `prompts/meal_audit.md` rewritten from a non-personalized critique into a
     **performance-fueling coach** (target-vs-actual gap analysis, always improve + keep,
     periodize carbs by the day's training, forward-looking) and **wired into the chat path**
     (`core/main.py`, previously crons-only) + the morning-briefing "Fuel plan for today".
     `nutrition_targets` seeded with build-goal anchors.
  2. *HealthKit re-sync duplication fix* (rev `klaus-agent-00101-pbm`): the Shortcut re-sends the
     whole day on every Lifesum close (~9×/day); the synthetic `source_id` embedded integer
     calories, so a meal-time whose total drifted between syncs minted a NEW Firestore doc →
     totals ~60% high (lunch stored as both 1177 and 1180 kcal). Fixed: `_compute_source_id` keys
     on `(start_date, food_item)` only (mirrors the aggregator); `MealStore.get_day` dedupes
     `(timestamp, source)` keeping latest `updated_at` (corrects history on read).
     `scripts/dedupe_healthkit_meals.py --apply` run 2026-06-09: 18 legacy dup docs purged across
     30 days (storage now matches reads; verified raw_docs == get_day count).
  3. *Centralized, Garmin-synced bodyweight* (rev `klaus-agent-00102-9nk`): weight is now a single
     top-level profile field `bodyweight_kg` (=73), auto-refreshed once/day from the latest Garmin
     weigh-in (`garmin_tool.fetch_garmin_weight`, grams→kg, sanity-bounded 30–250) via
     `morning_briefing._sync_bodyweight_from_garmin` (guarded on `bodyweight_synced_on`). Removed
     the duplicate `nutrition_targets.bodyweight_kg`. Chat coach + briefing + smart_agent read the
     one field. Amit updates weight by logging a Garmin weigh-in. Suite 1153 green. No new cron/secret.
     **Operator:** first real Garmin pull happens at the next morning briefing — confirm via logs.

- **Per-run Garmin detail capture** (2026-06-09, commits `0de5b2a` + `d72120f`, deployed via CI):
  gives running the same per-detail depth Hevy gave strength, so coaching is specific not generic.
  Root insight: Strava is the *wrong* source (downstream of Garmin, strips running dynamics); the
  installed `garminconnect` client already exposes per-activity detail Klaus never called. New
  `RunDetailStore` (Firestore `run_details`), `mcp_tools/garmin_tool.py::normalize_run_detail`
  (recorded laps as the watch lapped them — per-km easy/tempo, per-rep intervals — + whole-run
  min/avg/max summary + derived split_shape/hr_drift/cadence_drift/pace_cv; NOT raw streams),
  `core/run_ingest.py` (daily `/cron/run-sync` 05:15, presence-diff backfill→delta), brain-direct
  `get_run_detail` + fed into `get_training_context`, weekly review reads `run_details`, evening
  alert optional one-fact ride-along. **Calibration follow-up** (`d72120f`): first real use
  over-interpreted an easy run (called a watch-pause drink-stop a "negative split"); fixed by
  gating `split_shape` on ≥4 active laps + ≥4% swing (+ `active_lap_count`) and rewriting the
  run-coaching prompts to lead with an honest verdict and never narrate noise as strategy. No new
  secret (reuses `GARMIN_EMAIL`/`GARMIN_PASSWORD`). 37 new tests, suite 1138 green. DEPLOYMENT §19b.
  Operator: create `klaus-run-sync` job + drain backfill until done:true.

- **Training blocks = Training-calendar membership** (2026-06-08, deployed rev `klaus-agent-00095-hcf`): a training
  block is now defined as any event in the dedicated **Training** calendar (excluding its
  `Get Ready:`/`Travel:` buffer blocks), not by title keywords. Removed `WORKOUT_KEYWORDS`
  + bare-"Practice" auto-detection from `create_event` (`is_workout` defaults to False; the
  brain decides per event). Read paths follow suit: evening **weather alerts** source
  tomorrow's Training-calendar events (with a decoupled `_OUTDOOR_KEYWORDS` filter for
  indoor/outdoor weather-sensitivity only), and **nutrition anchors** split AM/PM by start
  time over Training events instead of keywords (the previously-dead calendar fallback is
  now live). `list_calendar_events` merges primary + Training events (tagged + sorted) so
  the brain can see training blocks. Tradeoff: weather alerts no longer warn about
  non-training outdoor events in the *primary* calendar. `is_free` still primary-only
  (pre-existing). Files: `mcp_tools/calendar_tool.py`, `core/tools.py`,
  `core/proactive_alerts.py`, `prompts/smart_agent.md`, `docs/USER.md`. Suite 1101 green.
  Shipped in commit `f4c424f`, deployed via CI/CD to Cloud Run rev `klaus-agent-00095-hcf`.

- **Hevy strength integration** (2026-06-08, deployed rev `klaus-agent-00093-dww`):
  full per-set workout sync from Hevy (Pro API, daily pull `/cron/strength-sync`,
  backfill→delta). New `StrengthSessionStore`, `mcp_tools/hevy_tool.py`,
  `core/strength_ingest.py`, brain-direct tools `get_strength_progress` +
  `get_training_context` (unified cross-domain coaching), weekly review now reads
  `strength_sessions` with a loosened "think, don't fill a template" prompt.
  Backfill verified: 35 workouts (2023→2026) in Firestore. 35 new tests, suite 1096 green.
  Docs: `docs/hevy_integration.md`, DEPLOYMENT §19a/§20a.

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-08 after v4.0)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** v4.0 + Hevy + per-run Garmin detail + nutrition (accurate/training-aware coaching, HealthKit dedup, Garmin-synced bodyweight) increments live (rev `klaus-agent-00102-9nk`). Planning next milestone — run `/gsd-new-milestone`.

## Architecture (current)

- Brain `gemini-3.5-flash` (AI Studio) · Worker `deepseek-v4-flash` (DeepSeek) · Fallback `claude-haiku-4-5` (Anthropic, inline) · Tick-brain `qwen3-32b` (Groq, free) + Gemini fallback
- Embeddings `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404); `load_dotenv(override=True)` always
- Postgres holds the 3-year Garmin backfill; `MealStore` + `TrainingLogStore` + `StrengthSessionStore` (Hevy per-set) + `RunDetailStore` (Garmin per-run) in Firestore; `UserProfileStore` now populated with Amit's living blueprint (v4.0 Phase 21); `BlockStore` + `BenchmarkStore` + `CoachingTopicStore` added in v4.0
- 10 cron jobs deployed (v4.0 added none; post-v4.0 added `klaus-strength-sync` 05:00 Hevy pull + `klaus-run-sync` 05:15 Garmin per-run detail pull)

## Accumulated Context

### Decisions

Recent decisions affecting v4.0 (full log in PROJECT.md):

- [v4.0 research]: `docs/COACHING_GUIDE.md` injected as `{coaching_guide}` via `_load_coaching_guide()` — same startup-cache pattern as `_load_self_md()`. NOT Pinecone RAG.
- [v4.0 research]: D-13 release is prompt-only. Tier A (blueprint goals) citable as targets; Tier B (measured data) citable only within recency window (lifts ≤14d, pace ≤7d, nutrition ≤2d). Same commit as guard removal.
- [v4.0 research]: Block-end benchmark trigger via `benchmark_due` flag in `BlockStore` checked by the existing 21:30 cron — no 8th scheduler job.
- [v4.0 research]: `BlockStore` + `BenchmarkStore` as dedicated Firestore stores (not extending `TrainingLogStore`). Doc ID `{date}_{facet}` makes benchmark logging idempotent.
- [v4.0 research]: Cross-cron coaching dedup via `OutreachLogStore` extension (or thin `CoachingTouchStore`), covering morning briefing + evening check-in + weekly review + autonomous tick. Not just the autonomous tick.
- [v4.0 research]: Plan_start_date = 2026-06-21 (Week 1 anchor). Week number always derived from `(today - plan_start_date).days // 7 + 1` — never hardcoded.
- [Phase ?]: Phase 25 Plan 01

### Pending Todos

None captured yet.

### Blockers/Concerns

None.

## Deferred Items

Carried forward from v3.0 close:

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| verification-gap | 19-VERIFICATION.md `human_needed` | acknowledged | Phase 19 functionality verified live; paperwork only |
| feature-followup | Weekly review "Garmin activities unavailable" | open (low priority) | confirm 14-day fetch vs genuinely empty watch |
| verification-gap | v2.0 SC-1/SC-2/SC-4 live-staging | acknowledged | operator triggers staging crons |
| code-quality | 18-REVIEW.md M-2..M-4 + L-1..L-5 | open (housekeeping) | next housekeeping sprint |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops before v2.0 | open (low priority) | next docs sweep |

## Notes

- **Test env:** full `pytest tests/` segfaults in one process (grpc/protobuf GC, Python 3.13) — verify per-file. 630+ passing baseline must hold after every v4.0 phase.
- **Firestore SERVER_TIMESTAMP** reads back as `DatetimeWithNanoseconds` — ISO-convert before `json.dumps` in any read tool. See `_jsonsafe_doc` helper in `memory/firestore_db.py`.
- **Cron jobs (10):** heartbeat (hourly), proactive-alerts (21:30), morning-briefing (*/10 6-10), chat-ingest (04:00), chat-export-ingest (04:30), reflect (22:00), autonomous-tick (*/20 7-21), weekly-training-review (Sun 10:00), strength-sync (05:00, Hevy pull), run-sync (05:15, Garmin per-run detail pull). Plus push-driven `/cron/healthkit-sync`.

## Session Continuity

Last session: 2026-06-08T08:30:00Z
Stopped at: Phase 25 Plan 03 complete — all tasks executed, SUMMARY.md created
Resume file: None

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
