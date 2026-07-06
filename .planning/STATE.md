---
gsd_state_version: 1.0
milestone: v5.0
milestone_name: Klaus Hub
status: planning
stopped_at: Phase 30 context gathered
last_updated: "2026-07-06T11:04:50.209Z"
last_activity: 2026-07-06
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 31
  completed_plans: 31
  percent: 80
---

# State — Klaus

## Current Position

Phase: 30
Plan: Not started
Status: Ready to plan
Last activity: 2026-07-06

**Progress bar:** [██--------] 20% (1/5 phases)

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
  gives running the same per-detail depth Hevy gave strength. New `RunDetailStore` (Firestore
  `run_details`), `mcp_tools/garmin_tool.py::normalize_run_detail`, `core/run_ingest.py`
  (daily `/cron/run-sync` 05:15, presence-diff backfill→delta), brain-direct `get_run_detail` +
  fed into `get_training_context`, weekly review reads `run_details`. Suite 1138 green.

- **Training blocks = Training-calendar membership** (2026-06-08, deployed rev `klaus-agent-00095-hcf`):
  training block defined as any event in the Training calendar. Removed `WORKOUT_KEYWORDS`.
  Suite 1101 green.

- **Hevy strength integration** (2026-06-08, deployed rev `klaus-agent-00093-dww`):
  full per-set workout sync from Hevy (Pro API, daily pull `/cron/strength-sync`, backfill→delta).
  New `StrengthSessionStore`, `mcp_tools/hevy_tool.py`, `core/strength_ingest.py`. Suite 1096 green.

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-13 for v5.0)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 30 — health pages

## Architecture (current)

- Brain `gemini-3.5-flash` (AI Studio) · Worker `deepseek-v4-flash` (DeepSeek) · Fallback `claude-haiku-4-5` (Anthropic, inline) · Tick-brain `qwen3-32b` (Groq, free) + Gemini fallback
- Embeddings `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404); `load_dotenv(override=True)` always
- Postgres holds the 3-year Garmin backfill; `MealStore` + `TrainingLogStore` + `StrengthSessionStore` (Hevy per-set) + `RunDetailStore` (Garmin per-run) in Firestore; `UserProfileStore` populated with Amit's living blueprint; `BlockStore` + `BenchmarkStore` + `CoachingTopicStore` added in v4.0
- 10 cron jobs deployed (heartbeat hourly, proactive-alerts 21:30, morning-briefing */10 6-10, chat-ingest 04:00, chat-export-ingest 04:30, reflect 22:00, autonomous-tick */20 7-21, weekly-training-review Sun 10:00, strength-sync 05:00, run-sync 05:15; plus push-driven `/cron/healthkit-sync`)
- **v5.0 adds:** React + TypeScript + Vite PWA frontend (Tailwind), served by FastAPI from the `klaus-agent` container; `TaskStore`, `HabitStore`, `PushSubscriptionStore` (new Firestore stores); `/api/*` routes with Google session auth; Web Push (VAPID); multi-stage Dockerfile (Node build stage)

## v5.0 Roadmap Summary

| Phase | Goal | Requirements |
|-------|------|--------------|
| 26 - Hub Shell | Amit can open the hub on phone/desktop, sign in, see the Today timeline, and chat with Klaus | HUB-01..05, CHAT-01..04, TIME-01..05, TIME-07, TIME-08 (16 reqs) |
| 27 - Tasks | Native TaskStore replaces TickTick; hub task pages with recurrence, quick-add, micro-animation | TASK-01..07 (7 reqs) |
| 28 - Habits & Supplements | HabitStore with check-offs, streaks, Klaus adherence awareness, habits on timeline | HABIT-01..05, TIME-06 (6 reqs) |
| 29 - Web Push & Transition | VAPID push notifications on iPhone, Telegram mirror flag, unread badge | PUSH-01..04 (4 reqs) |
| 30 - Health Pages | Training history, nutrition detail, sleep/recovery trend visualizations | HLTH-01..03 (3 reqs) |

## Accumulated Context

### Decisions

- [v5.0 design spec 2026-06-13]: Frontend is React + TypeScript + Vite PWA with Tailwind, served by FastAPI from `klaus-agent` — same origin, no CORS, one deploy.
- [v5.0 design spec 2026-06-13]: Auth is Google Sign-In allowlisted to Amit's account only → session cookie. All hub routes under `/api/*`; existing Telegram/cron/internal routes untouched.
- [v5.0 design spec 2026-06-13]: Chat reuses Firestore conversation history from `memory/firestore_conversation.py` — one shared history with Telegram. Hub POST → Cloud Tasks → `/internal/process-hub-message` (same full-CPU path as Telegram).
- [v5.0 design spec 2026-06-13]: Nutrition is display-only in the hub. Lifesum → HealthKit pipeline is unchanged; no second entry path.
- [v5.0 design spec 2026-06-13]: Supplements are habit-style daily check-offs with a dose field in `HabitStore`; no inventory management.
- [v5.0 design spec 2026-06-13]: TIME-06 (habits on timeline) depends on `HabitStore` → belongs to Phase 28 (habits phase), not Phase 26.
- [v5.0 design spec 2026-06-13]: TASK-07 (tasks on glance rail + timeline) depends on `TaskStore` → belongs to Phase 27 (tasks phase).
- [v5.0 design spec 2026-06-13]: Phase 26 requires a multi-stage Dockerfile (Node build stage) to produce built frontend assets served by FastAPI.
- [v5.0 design spec 2026-06-13]: Phases 27 (Tasks), 28 (Habits), 29 (Push), 30 (Health) all depend on Phase 26 (shell) but are independent of each other and can be built in any order after Phase 26.
- [v5.0 design spec 2026-06-13]: Telegram mirror flag (PUSH-03) must be left ON for at least one week of real production use before being disabled — Telegram retirement is a gradual transition, not a hard cutover.
- [Phase ?]: avoids duplicate color declarations
- [28-03 D-15]: habit_pending is a Layer-0 gather trigger (non-empty list wakes tick-brain at $0 cost, D-15 per-slot salience)
- [28-03 D-17]: per-item dedup topic key = plain string habit-nudge:{habit_id}:{today_iso} (CoachingTopicStore, Pitfall 4)
- [28-03 D-01]: SLOT_SUPPLEMENTS kept unchanged as fallback; _get_supplement_checkoffs overlays real HabitStore data when available
- [28-03 D-18]: Bedtime/pre-bed supplements outside the 7-21 tick window — 21:30 alert covers that slot cleanly

### Pending Todos

- Deploy the Groq tick-brain fix + tuned triage prompt (ready as of 2026-06-12) — ships together: `core/tick_brain.py` fixes, request-shape fixes (max_tokens 2048, temperature 0.6), tuned `prompts/autonomous_triage.md`. No Cloud Run env changes needed.

### Blockers/Concerns

None.

## Deferred Items

Carried forward from v4.0 close:

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| verification-gap | 19-VERIFICATION.md `human_needed` | acknowledged | Phase 19 functionality verified live; paperwork only |
| feature-followup | Weekly review "Garmin activities unavailable" | open (low priority) | confirm 14-day fetch vs genuinely empty watch |
| verification-gap | v2.0 SC-1/SC-2/SC-4 live-staging | acknowledged | operator triggers staging crons |
| code-quality | 18-REVIEW.md M-2..M-4 + L-1..L-5 | open (housekeeping) | next housekeeping sprint |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops before v2.0 | open (low priority) | next docs sweep |
| nyquist-partial | P21 missing VALIDATION.md; P23/P25 drafts `nyquist_compliant: false` | acknowledged | retroactive via `/gsd-validate-phase` if desired |
| design-note | WR-01: cron `plan_start_date` hardcode (D-03) | accepted | n/a |
| design-note | WR-02: `fueling_timeline` not gathered into crons (D-11) | accepted | n/a |

## Notes

- **Test env:** full `pytest tests/` segfaults in one process (grpc/protobuf GC, Python 3.13) — verify per-file. 1153+ passing baseline must hold after every v5.0 phase.
- **Firestore SERVER_TIMESTAMP** reads back as `DatetimeWithNanoseconds` — ISO-convert before `json.dumps` in any read tool. See `_jsonsafe_doc` helper in `memory/firestore_db.py`.
- **Cron jobs (10):** heartbeat (hourly), proactive-alerts (21:30), morning-briefing (*/10 6-10), chat-ingest (04:00), chat-export-ingest (04:30), reflect (22:00), autonomous-tick (*/20 7-21), weekly-training-review (Sun 10:00), strength-sync (05:00, Hevy pull), run-sync (05:15, Garmin per-run detail pull). Plus push-driven `/cron/healthkit-sync`.
- **Slot timestamps caveat:** HealthKit/Lifesum meal timestamps are canonical slot times (08:00/12:00/20:00), NOT actual eating times — never build UI that infers eating time from them.
- **GCP resource casing:** All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404).
- **Python version:** venv must be Python 3.11 (prod Dockerfile) or 3.13 (local) — NEVER 3.14 (grpc/protobuf GC segfault).
- **Agent turns:** Must run inside a tracked Cloud Tasks request (`/internal/process-update` or `/internal/process-hub-message`) — never in a Starlette BackgroundTask (CPU throttled after response).

## Session Continuity

Last session: 2026-07-06T11:04:50.206Z
Stopped at: Phase 30 context gathered
Resume file: .planning/phases/30-health-pages/30-CONTEXT.md

## Operator Next Steps

- Run `/gsd:plan-phase 26` to begin Phase 26 planning (Hub Shell)
- Deploy the pending Groq tick-brain fix + tuned triage prompt (no Cloud Run env changes needed)
