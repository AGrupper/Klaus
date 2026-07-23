---
gsd_state_version: 1.0
milestone: v6.0
milestone_name: Klaus Becomes an Agent
status: ready_to_plan
stopped_at: Phase 32 complete (8/8) — ready to discuss Phase 33
last_updated: 2026-07-23T04:06:07.122Z
last_activity: 2026-07-22 -- Phase 32 execution started
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 22
  completed_plans: 22
  percent: 33
---

# State — Klaus

## Current Position

Phase: 33
Plan: Not started
Status: Ready to plan
Last activity: 2026-07-23

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

See: `.planning/PROJECT.md` (updated 2026-07-17 for v6.0)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 33 — occasion cascade

## Architecture (current)

- Brain `gemini-3.5-flash` (AI Studio) · Worker `deepseek-v4-flash` (DeepSeek) · Fallback `claude-haiku-4-5` (Anthropic, inline) · Tick-brain `openai/gpt-oss-120b` (Groq, free, migrated pre-milestone 2026-07-16) + Gemini fallback
- **v6.0 will change:** Brain → `claude-sonnet-5` (Phase 30.5, Gemini flips to fallback); tick-brain fallback decoupled to explicit `TICK_BRAIN_FALLBACK_*` env (Phase 30.5, must ship before the brain flip)
- Embeddings `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404); `load_dotenv(override=True)` always
- Postgres holds the 3-year Garmin backfill; `MealStore` + `TrainingLogStore` + `StrengthSessionStore` (Hevy per-set) + `RunDetailStore` (Garmin per-run) in Firestore; `UserProfileStore` populated with Amit's living blueprint; `BlockStore` + `BenchmarkStore` + `CoachingTopicStore` added in v4.0
- 10 cron jobs deployed (heartbeat hourly, proactive-alerts 21:30, morning-briefing */10 6-10, chat-ingest 04:00, chat-export-ingest 04:30, reflect 22:00, autonomous-tick */20 7-21, weekly-training-review Sun 10:00, strength-sync 05:00, run-sync 05:15; plus push-driven `/cron/healthkit-sync`)
- v5.0 added: React + TypeScript + Vite PWA frontend (Tailwind), served by FastAPI from the `klaus-agent` container; `TaskStore`, `HabitStore`, `PushSubscriptionStore` (new Firestore stores); `/api/*` routes with Google session auth; Web Push (VAPID); multi-stage Dockerfile (Node build stage)
- **v6.0 adds (planned):** `StandingDirectiveStore` (Phase 31); `get_recent_window()` on `FirestoreConversationStore` + per-message `ts` (Phase 31); ambient Pinecone auto-recall on the chat path, `conversation_tail`/`training_reality`/`location` gather jobs, `forget_memory` tool, Groq daily token ledger (Phase 32); `occasion` parameter on `run_autonomous_tick`, `get_recent_decisions` tool, `OCCASION_CASCADE` flag (Phase 33); calendar-handler write-back hooks into `TrainingLogStore` (Phase 34); `proactive_alerts.py` + TickTick/worktree residue deleted, chat-ingest crons paused (Phase 35)

## v6.0 Roadmap Summary

| Phase | Goal | Requirements |
|-------|------|--------------|
| 30.5 - Brain Upgrade (Sonnet 5) | Smart brain runs on claude-sonnet-5 with prompt caching, truthful cost metering, decoupled tick-brain fallback, daily-spend tripwire, slimmed prompt | BRAIN-01..07 (7 reqs) |
| 31 - Standing Directives | Amit's lasting behavioral wishes are captured, injected into every reasoning path, listable/cancellable, and self-proposed from reflection | DIR-01..07 (7 reqs) |
| 32 - Unified Situation (Ambient Memory) | Ambient auto-recall, conversation continuity, reconciled training reality reach every reasoning path as context-only signals | MEM-01..07 (7 reqs) |
| 33 - Occasion Cascade | Nightly/morning/weekly become judgment-driven occasions through the shared cascade; silence is a valid, explainable outcome | OCC-01..07 (7 reqs) |
| 34 - Write-Backs | Calendar workout actions + chat-reported training changes mechanically and idempotently update TrainingLogStore | WB-01..04 (4 reqs) |
| 35 - Hardening & Subtraction | New eval fixtures, token-budget guard test, dead-code deletion, updated invariants | HARD-01..05 (5 reqs) |

See `.planning/ROADMAP.md` for full phase detail (goals, dependencies, success criteria).

## v5.0 Roadmap Summary (shipped 2026-07-09)

| Phase | Goal | Requirements |
|-------|------|--------------|
| 26 - Hub Shell | Amit can open the hub on phone/desktop, sign in, see the Today timeline, and chat with Klaus | HUB-01..05, CHAT-01..04, TIME-01..05, TIME-07, TIME-08 (16 reqs) |
| 27 - Tasks | Native TaskStore replaces TickTick; hub task pages with recurrence, quick-add, micro-animation | TASK-01..07 (7 reqs) |
| 28 - Habits & Supplements | HabitStore with check-offs, streaks, Klaus adherence awareness, habits on timeline | HABIT-01..05, TIME-06 (6 reqs) |
| 29 - Web Push & Transition | VAPID push notifications on iPhone, Telegram mirror flag, unread badge | PUSH-01..04 (4 reqs) |
| 30 - Health Pages | Training history, nutrition detail, sleep/recovery trend visualizations | HLTH-01..03 (3 reqs) |

## Accumulated Context

### Decisions

- [v6.0 roadmap 2026-07-17]: Phase numbering follows the approved plan's own labels — 30.5, 31, 32, 33, 34, 35 (decimal 30.5 deliberate, precedent: v3.0's 19.1–19.3). Not renumbered to 31–36.
- [v6.0 roadmap 2026-07-17]: Phase sequencing is dependency-locked per `.planning/research/ARCHITECTURE.md`'s verified build order — BRAIN-03 (tick-brain fallback decoupling) must deploy before the brain model flip within Phase 30.5; `get_recent_window()` lands in Phase 31 (not 32) because the reflection learning-loop fix needs it immediately; MEM-05's context-only invariant + Groq ledger must be complete before Phase 33 routes nightly/morning traffic through triage; OCC-06's flag rollout requires a 3-4 day observation window before legacy composer deletion in Phase 35.
- [v6.0 roadmap 2026-07-17]: `core/autonomous.py` must never import `core/nightly_review.py` — the shared `planned_sessions_for()` primitive routes through the neutral `core/training_checkin.py` module instead.
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
- [Phase 31]: veto() modeled exactly on cancel()/expire() (get-then-update, cache-invalidate, never hard-delete); get() added as a cheap never-raises single-doc read so the cancel handler can route on origin without a full-collection scan

### Pending Todos

- Deploy the Groq tick-brain fix + tuned triage prompt (ready as of 2026-06-12) — ships together: `core/tick_brain.py` fixes, request-shape fixes (max_tokens 2048, temperature 0.6), tuned `prompts/autonomous_triage.md`. No Cloud Run env changes needed.
- Re-verify Phase 31 now that both `31-VERIFICATION.md` gaps (DIR-05/D-16 supersedes routing via 31-07; DIR-07/D-13 vetoed-directive writer via 31-08) are closed, then start v6.0 Phase 32 (Unified Situation / Ambient Memory) planning.

### Blockers/Concerns

None.

## Deferred Items

Acknowledged and deferred at the v5.0 milestone close on 2026-07-09:

| Category | Item | Status |
|----------|------|--------|
| uat-verification | v5.0 P29 physical-device push (iPhone PWA push delivery on a real device) | acknowledged |
| uat-verification | v5.0 P29 Telegram-mirror parallel week before disabling the mirror (PUSH-03, by design) | acknowledged |
| ux-polish | v5.0 P26 cosmetic UX polish (chat scroll, leave-by chip live-check, icon art, error-boundary) — tracked in `26-HUMAN-UAT.md` | deferred |

Carried forward from v4.0 close (still open):

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| verification-gap | 19-VERIFICATION.md `human_needed` | acknowledged | Phase 19 functionality verified live; paperwork only |
| feature-followup | Weekly review "Garmin activities unavailable" | open (low priority) | confirm 14-day fetch vs genuinely empty watch |
| verification-gap | v2.0 SC-1/SC-2/SC-4 live-staging | acknowledged | operator triggers staging crons |
| code-quality | 18-REVIEW.md M-2..M-4 + L-1..L-5 | open (housekeeping) | next housekeeping sprint |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops before v2.0 | open (low priority) | next docs sweep |
| nyquist-partial | v4.0 P21 missing VALIDATION.md; P23/P25 drafts `nyquist_compliant: false` (v5.0 P27/28/29 validated at close) | acknowledged | retroactive via `/gsd-validate-phase` if desired |
| design-note | WR-01: cron `plan_start_date` hardcode (D-03) | accepted | n/a |
| design-note | WR-02: `fueling_timeline` not gathered into crons (D-11) | accepted | n/a |

## Notes

- **Test env:** full `pytest tests/` segfaults in one process (grpc/protobuf GC, Python 3.13) — verify per-file. 1775+ backend passing baseline must hold after every v6.0 phase.
- **Firestore SERVER_TIMESTAMP** reads back as `DatetimeWithNanoseconds` — ISO-convert before `json.dumps` in any read tool. See `_jsonsafe_doc` helper in `memory/firestore_db.py`.
- **Cron jobs (10):** heartbeat (hourly), proactive-alerts (21:30), morning-briefing (*/10 6-10), chat-ingest (04:00), chat-export-ingest (04:30), reflect (22:00), autonomous-tick (*/20 7-21), weekly-training-review (Sun 10:00), strength-sync (05:00, Hevy pull), run-sync (05:15, Garmin per-run detail pull). Plus push-driven `/cron/healthkit-sync`. v6.0 Phase 35 will pause chat-ingest + chat-export-ingest (code kept) and delete `proactive_alerts.py` (route confirm-dormant first) — no new Cloud Scheduler jobs added this milestone.
- **Slot timestamps caveat:** HealthKit/Lifesum meal timestamps are canonical slot times (08:00/12:00/20:00), NOT actual eating times — never build UI that infers eating time from them.
- **GCP resource casing:** All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404).
- **Python version:** venv must be Python 3.11 (prod Dockerfile) or 3.13 (local) — NEVER 3.14 (grpc/protobuf GC segfault).
- **Agent turns:** Must run inside a tracked Cloud Tasks request (`/internal/process-update` or `/internal/process-hub-message`) — never in a Starlette BackgroundTask (CPU throttled after response).
- **v6.0 sequencing constraints (do not reorder):** tick-brain fallback decoupling before the brain model flip (both within Phase 30.5); `get_recent_window()` before the reflection learning-loop fix (both within Phase 31); context-only invariant + Groq ledger complete before Phase 33 routes occasion traffic through triage; `OCCASION_CASCADE` flag introduction (Phase 33) strictly before legacy composer deletion (Phase 35) — never collapsed into one change.

## Session Continuity

Last session: 2026-07-22T13:58:57.223Z
Stopped at: Phase 32 context gathered
Resume file: .planning/phases/32-unified-situation-ambient-memory/32-CONTEXT.md

## Operator Next Steps

- Both `31-VERIFICATION.md` gaps are closed (DIR-05/D-16 via 31-07, DIR-07/D-13 via 31-08). Re-verify Phase 31, then start v6.0 Phase 32 (Unified Situation / Ambient Memory) planning: `/gsd:plan-phase 32`.
