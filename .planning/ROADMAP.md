# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## v3.0 — Project Shifu (Phases 19–20) — In Progress (started 2026-05-25)

Gives Klaus athletic coaching capability: he reads his own Garmin training data
from Postgres, ingests nutrition from Lifesum via Google Fit for both mid-day
coaching and morning recap, holds the user accountable to logged sessions,
and lets recovery state (ACWR / HRV / sleep) shape the morning briefing tone.
Plumbing-only — personalized rules and thresholds are deferred to a later
session via `UserProfileStore` writes.

**Phases:** 5 · **Plans:** 5 (Phase 19) + 5 (Phase 19.1) + TBD (Phase 19.2) + TBD (Phase 19.3) + TBD (Phase 20) · **Requirements:** 53

### Phases

- [x] **Phase 19: Training Awareness & Nutrition Coaching** — Schema migration, 3-year Garmin backfill, `UserProfileStore`, extended Garmin reads (training status, recent activities, ACWR), Google Fit nutrition fetch + `MealStore`, autonomous-tick mid-day coaching extension, morning nutrition recap, smart-agent prompt extension.  *(SC #2 closed by Phase 19.1 on 2026-05-30)*
- [x] **Phase 19.1: HealthKit Nutrition Bridge** — Gap-closure for Phase 19 SC #2 on iOS. iOS Personal Automation on Lifesum-close emits flat per-quantity HealthKit samples → `POST /cron/healthkit-sync` (shared-secret bearer) → server-side aggregation by (start_date, food_item) → normalize → existing `MealStore.upsert`. Live UAT verified 2026-05-30 01:11 — real Lifesum meal landed in Firestore with correct macros.
- [x] **Phase 19.2: Fiber Through Reasoning Layer** *(INSERTED)* — Post-ship follow-up to 19.1. The HealthKit Shortcut already emits `DietaryFiber_g` but the normalizer drops it; persist fiber through the meal pipeline (normalizer + `MealStore`) and surface it in Klaus's reasoning/briefings. Explicitly requested by Amit (2026-05-29). **Fixed inline 2026-05-30:** `fiber_g` threaded through `healthkit_tool._normalize_healthkit_sample` (10-key dict) + `google_fit_tool._normalize_point` + `MealStore.get_day_aggregate` totals + `meal_audit.md` fiber heuristic. Code-complete + tested (638 pass); live re-verify pending deploy.
- [x] **Phase 19.3: Meal Read Paths → iOS HealthKit (MealStore)** *(INSERTED)* — Post-ship follow-up to 19.1. BOTH meal *read* paths still query the dead Google Fit source (returns `[]` on iOS), so HealthKit-ingested meals are invisible to Klaus: (a) the brain-direct `fetch_recent_meals` tool at `core/tools.py:1267` (`_handle_fetch_recent_meals` → `google_fit_tool.fetch_recent_meals`) — confirmed live 2026-05-30 16:07 ("no entries in Google Fit or Lifesum"); (b) the mid-day autonomous tick at `core/autonomous.py:319` (`sync_recent_meals()`). Redirect both to read the shared `MealStore` (where `/cron/healthkit-sync` writes), matching the morning briefing's already-correct `MealStore` path. Found during 19.1 UAT (2026-05-30).
- [ ] **Phase 20: Accountability Crons & Recovery Briefing** — `TrainingLogStore`, evidence-first training check-in cron (Garmin-RPE-aware), weekly training review cron, `recovery_concern` flag in morning briefing, Cloud Scheduler bootstrap.

### Phase Details

### Phase 19: Training Awareness & Nutrition Coaching
**Goal**: Klaus can read his own training/recovery/nutrition data, coach proactively on meals mid-day, and recap nutrition in the morning briefing — with an empty profile scaffold ready for personalization.
**Depends on**: Nothing (Postgres infra from commit `2c8be7a` is in place; Google OAuth already wired)
**Requirements**: SCHEMA-01, SCHEMA-02, SCHEMA-03, INGEST-01, INGEST-02, INGEST-03, PROFILE-01, PROFILE-02, PROFILE-03, PROFILE-04, GARMIN-01, GARMIN-02, GARMIN-03, GARMIN-04, GARMIN-05, NUTR-01, NUTR-02, NUTR-03, NUTR-04, NUTR-05, NUTR-06, NUTR-07, NUTR-08, PROMPT-01, PROMPT-02, PROMPT-03
**Success Criteria** (what must be TRUE):
  1. Asking Klaus "what was my ACWR this week?" in Telegram returns a real number computed from Postgres (or an honest "chronic baseline insufficient" answer when too little history).
  2. After logging a meal in Lifesum, within ~30 min Google Fit shows the nutrition entry; within the next autonomous tick (≤20 min after that) `meals/{date}/{timestamp}` appears in Firestore with macros + meal type. If the meal is notable (e.g., very low protein before a workout, large gap since last meal), Klaus may proactively reach out via Telegram mid-day — repeat-suppressed per existing `OutreachLogStore` rules.
  3. After a 3-year Garmin backfill, a `database_tool.py` query against `activities` and `daily_biometrics` returns populated `training_load`, `perceived_exertion`, `feel`, and `vo2_max` columns with documented row counts and NULL rates.
  4. On cold start, `users/amit` exists in Firestore with the empty scaffold (`athletic_goals: []`, `training_constraints: []`, `recovery_preferences: {}`, `schema_version: 1`); `get_training_profile` returns it via brain-direct call.
  5. Morning briefing on a day after meals were logged includes a yesterday-nutrition recap (totals + biggest gap). On a day with no meals logged, the recap is silently omitted (no "no data" placeholder).
  6. `docs/SELF.md` regenerated by `core/self_manifest.py` lists the new tools (`get_training_profile`, `update_training_profile`, `fetch_training_status`, `fetch_recent_activities`, `fetch_recent_meals`).
**Plans**: 5
- [x] 19-01-PLAN.md — Postgres schema migration + Garmin parser extensions + INGEST-03 backfill checkpoint (SCHEMA-01..03, INGEST-01..03) — completed 2026-05-27
- [x] 19-02-PLAN.md — UserProfileStore fill-in + Garmin live reads + compute_acwr + 4 tool registrations (PROFILE-01..04, GARMIN-01..04) — completed 2026-05-27
- [x] 19-03-PLAN.md — Google Fit OAuth scope + google_fit_tool + MealStore + fetch_recent_meals registration (NUTR-01..03) — completed 2026-05-27
- [x] 19-04-PLAN.md — Autonomous-tick gather extensions + morning-briefing nutrition recap + Postgres biometrics writeback + eval fixture schema lock (NUTR-04, NUTR-05, GARMIN-05) — completed 2026-05-27
- [x] 19-05-PLAN.md — render_smart_system extension + 4 prompt updates + SELF.md regen (PROMPT-01..03, NUTR-06..08) — completed 2026-05-28
**UI hint**: yes

### Phase 19.1: HealthKit Nutrition Bridge
**Goal**: Close Phase 19 SC #2 on iOS by bridging Apple HealthKit dietary samples (where Lifesum writes on iPhone) into the existing `MealStore`, so the autonomous tick's `meals_since_last_tick` trigger fires on real data.
**Depends on**: Phase 19 (needs `MealStore`, autonomous-tick gather wiring, eval fixture schema)
**Requirements**: HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03, HEALTHKIT-04, HEALTHKIT-05, HEALTHKIT-06, HEALTHKIT-07, HEALTHKIT-08
**Success Criteria** (what must be TRUE):
  1. After logging a meal in Lifesum on iPhone, the iOS Shortcut "On Lifesum close" fires, POSTs to `/cron/healthkit-sync`, and within ~20 min the next autonomous tick sees the meal in `meals_since_last_tick` and may proactively reach out via Telegram (repeat-suppressed per `OutreachLogStore`).
  2. Daily 23:55 iOS Shortcut catch-up sweeps the last 24h of HealthKit dietary samples; re-pushed meals do not double-count (idempotent on `source_id = "healthkit:{HKObject.UUID}"`).
  3. Heartbeat cron raises a staleness alarm if no `/cron/healthkit-sync` push has been recorded in the last 48h (catches silent bridge breakage).
  4. `docs/SELF.md` regenerated by `core/self_manifest.py` lists a new "Push endpoints" section with `/cron/healthkit-sync` as the only entry.
  5. Re-running Phase 19 SC #2 end-to-end (Lifesum meal → Firestore `meals/{date}/timestamps/healthkit:*` doc → tick-brain judgment → optional Telegram nudge) succeeds against deployed Cloud Run.
  6. Google Fit path in `mcp_tools/google_fit_tool.py` is preserved and marked legacy via docstring; `MealStore` schema is unchanged (multi-source).
**Plans**: 5
- [ ] 19.1-01-PLAN.md — Real-device fixture + schema-lock harness + REQUIREMENTS/ROADMAP registration (HEALTHKIT-01)
- [ ] 19.1-02-PLAN.md — `mcp_tools/healthkit_tool.py` Pydantic model + normalizer (HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03)
- [ ] 19.1-03-PLAN.md — `POST /cron/healthkit-sync` route + `_verify_healthkit_request` auth helper (HEALTHKIT-04, HEALTHKIT-05)
- [ ] 19.1-04-PLAN.md — Heartbeat staleness key + SELF.md Push endpoints + DEPLOYMENT.md sections + google_fit legacy marker (HEALTHKIT-06, HEALTHKIT-07)
- [ ] 19.1-05-PLAN.md — Operator push script + Shortcut runbook + live UAT (HEALTHKIT-08)
**UI hint**: yes

### Phase 19.2: Fiber Through Reasoning Layer *(INSERTED)*
**Goal**: `DietaryFiber_g` — already sent by the HealthKit Shortcut but dropped by the normalizer — is persisted through the meal pipeline and available to Klaus's reasoning, so fiber can inform nutrition coaching and morning recaps.
**Depends on**: Phase 19.1 (needs `healthkit_tool.py` normalizer/aggregator + `MealStore` schema)
**Requirements**: TBD (FIBER-01 — to register at plan time)
**Success Criteria** (what must be TRUE):
  1. A HealthKit push carrying `DietaryFiber_g` results in a `MealStore` document that retains the fiber value (no longer silently dropped by the normalizer).
  2. Fiber is exposed to Klaus's reasoning layer — `fetch_recent_meals` / the smart-agent meal view surfaces fiber, so asking about fiber intake returns a real number rather than omitting it.
  3. The morning nutrition recap (and/or autonomous-tick coaching) can reference fiber where relevant, without forcing a "no data" placeholder when fiber is absent.
  4. Existing meals without fiber and the multi-source `MealStore` schema remain backward-compatible (fiber is additive/optional).
**Plans**: TBD
**UI hint**: no

### Phase 19.3: Meal Read Paths → iOS HealthKit (MealStore) *(INSERTED)*
**Goal**: Every place Klaus *reads* meals — the on-demand "what did I eat?" tool and the mid-day autonomous tick — pulls from the shared `MealStore` (where the iOS HealthKit bridge writes), instead of the deprecated Google Fit source that returns nothing on iPhone. So both on-demand answers and proactive nudges reflect real logged meals.
**Depends on**: Phase 19.1 (needs `/cron/healthkit-sync` → `MealStore` write path live)
**Requirements**: TBD (MEALSRC-01 — to register at plan time)
**Success Criteria** (what must be TRUE):
  1. Asking Klaus "what did I eat today?" in Telegram after a HealthKit-ingested meal returns the real macros (NOT "no entries in Google Fit or Lifesum"). The brain-direct `fetch_recent_meals` tool (`core/tools.py:1267` `_handle_fetch_recent_meals`) reads `MealStore.get_day()`, not `google_fit_tool.fetch_recent_meals`.
  2. After a meal is ingested via `/cron/healthkit-sync`, the next autonomous tick's `meals_since_last_tick` contains that meal (read from `MealStore.get_day()`), so the tick-brain trigger can fire — verified against a HealthKit-sourced (not Google-Fit) meal. `core/autonomous.py:319` no longer calls `sync_recent_meals()` from `google_fit_tool`.
  3. Both repointed read paths keep the same meal-dict shape downstream consumers expect (the 9-key normalized record; triage prompt + `tests/test_evals.py` snapshot keys unchanged — no fixture-schema regression).
  4. A full audit confirms no remaining production caller depends on `google_fit_tool` for live meal data; `google_fit_tool.py` stays in the tree as legacy/no-op (docstring already marks it legacy from 19.1-04) — not deleted, just unreferenced.
  5. Repeat-suppression and the existing tick cost-gating (Layer 0 → 1 → 2) are unchanged — only the data source for the meal signal moves. `docs/SELF.md` tool description for `fetch_recent_meals` no longer claims Google Fit as the source.
**Plans**: TBD
**UI hint**: no

### Phase 20: Accountability Crons & Recovery Briefing
**Goal**: Klaus actively tracks training adherence and surfaces recovery concerns in the morning briefing.
**Depends on**: Phase 19 (needs `UserProfileStore`, Garmin reads, Postgres ACWR columns)
**Requirements**: LOG-01, LOG-02, LOG-03, LOG-04, CHECKIN-01, CHECKIN-02, CHECKIN-03, CHECKIN-04, CHECKIN-05, CHECKIN-06, REVIEW-01, REVIEW-02, REVIEW-03, REVIEW-04, RECOVERY-01, RECOVERY-02, RECOVERY-03, CRON-01, CRON-02
**Success Criteria** (what must be TRUE):
  1. On a typical day where Garmin already has RPE for every planned workout, the 21:30 training check-in (folded into the proactive-alerts cron) sends zero Telegram messages and the day's Garmin activities appear in `training_log` with `source="garmin"`.
  2. On a day where a planned workout has no Garmin record, the 21:30 check-in sends an inline-keyboard prompt ("Skipped or watch off?"); selecting a button writes a `training_log` entry and the follow-up notes prompt accepts `/skip` or a free-text reply.
  3. Morning briefing on an ACWR>1.5 day with a heavy session scheduled mentions recovery concern with a direct, metric-anchored tone shift (not commanding); on a normal day the same prompt produces the usual briefing without recovery framing.
  4. Sunday 10:00 weekly-review cron sends a Telegram message containing planned-vs-actual training, HRV/RHR/sleep trend lines, and one suggestion for the coming week, sourced from `training_log`, `activities`, `daily_biometrics`, and live `MealStore` 7-day totals.
  5. Operator running `scripts/bootstrap_shifu_crons.sh` creates the single `klaus-weekly-training-review` Cloud Scheduler job with OIDC auth (the training check-in needs no new job — it folds into proactive-alerts per D-09); the new job appears alongside the existing jobs in `docs/DEPLOYMENT.md` Phase Shifu section.
**Plans**: 7
- [x] 20-01-PLAN.md — TrainingLogStore + PendingPromptStore + log_training/get_training_history tools (LOG-01..04)
- [x] 20-02-PLAN.md — Reconcile REQUIREMENTS/ROADMAP for D-09 + D-21 (CHECKIN-01/06, REVIEW-02, CRON-01)
- [ ] 20-03-PLAN.md — send_and_inject reply_markup + router callback_query dispatch + Training-calendar read (CHECKIN-04)
- [ ] 20-04-PLAN.md — core/training_checkin.py (silent Garmin sync + branch + callbacks) folded into proactive-alerts (CHECKIN-01..06)
- [ ] 20-05-PLAN.md — RECOVERY_THRESHOLDS + compute_recovery_concern + morning_briefing/proactive_alert tone shift (RECOVERY-01..03)
- [ ] 20-06-PLAN.md — Weekly-review cron route + brain compose module + prompt + heartbeat staleness key (REVIEW-01..04)
- [ ] 20-07-PLAN.md — bootstrap_shifu_crons.sh + DEPLOYMENT.md Phase Shifu + SELF.md regen (CRON-01, CRON-02)
**UI hint**: yes

### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 19. Training Awareness & Nutrition Coaching | 5/5 | Complete (SC #2 closed by 19.1) | 2026-05-28 |
| 19.1. HealthKit Nutrition Bridge | 5/5 | Complete | 2026-05-30 |
| 19.2. Fiber Through Reasoning Layer *(INSERTED)* | inline | Code-complete (fixed inline; live re-verify pending) | 2026-05-30 |
| 19.3. Meal Read Paths → iOS HealthKit (MealStore) *(INSERTED)* | inline | Code-complete (fixed inline; live re-verify pending) | 2026-05-30 |
| 20. Accountability Crons & Recovery Briefing | 2/7 | In Progress|  |

Detail: full per-phase plans land in `.planning/phases/19-*/` and
`.planning/phases/20-*/` once `/gsd-plan-phase` runs. Archived to
`.planning/milestones/v3.0-ROADMAP.md` at milestone close.

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) ✓ Shipped 2026-05-23

Made Klaus self-aware, judgment-driven, cost-transparent: every LLM call
metered, free always-on tick-brain, self-inspect tools, doubt-free SELF.md
manifest + mutable self_state, daily reflection cron, and the autonomous
engine (`*/20 7-21` triage + compose pipeline with repeat-suppression +
eval harness).

**Phases:** 5 · **Plans:** 24 · **Requirements:** 41/41

| # | Phase | Outcome |
|---|-------|---------|
| 14 | Foundation: Cost Metering + Tick-Brain + LLM Strategy | `core/pricing.py`, `LLMUsageStore`, `core/tick_brain.py` (Groq/Qwen3-32B + Gemini fallback), per-purpose model map in `docs/TECHNICAL_PLAN.md` |
| 15 | Codebase Self-Knowledge | `mcp_tools/self_inspect.py` + 3 brain-direct tools (`list_own_files`, `read_own_source`, `search_own_source`) with secret denylist |
| 16 | Self-Model & State Awareness | `docs/SELF.md` auto-generated manifest, `SelfStateStore`, `get_self_status` tool, weekly SHA staleness check |
| 17 | Reflection & Journal | `core/reflection.py` + `JournalStore` + `/cron/reflect` (Cloud Scheduler ~22:00), Pinecone `kind="self"` |
| 18 | The Autonomous Engine | `core/autonomous.py` (3-layer pipeline: gather → triage → compose), `/cron/autonomous-tick` OIDC-protected, `FollowupStore`/`OutreachLogStore`/`TickLogStore`, `schedule_followup`/`list_followups`/`cancel_followup` tools, 5 seed eval fixtures, `scripts/eval_tick_brain.py` runner, full DEPLOYMENT.md |

Detail: see `.planning/milestones/v2.0-ROADMAP.md` and
`.planning/milestones/v2.0-REQUIREMENTS.md`.

**Deferred to staging smoke (see `.planning/STATE.md § Deferred Items`):**
SC-1, SC-2, SC-4 (require live Telegram + Cloud Run + real Groq key) — code
paths verified at unit-test level; final live-fire validation is a manual
operator step. SC-3 (quiet-tick cost ≈ $0) verified locally.

---

## v1.0 — Foundation & Integrations (Phases 1–13) ✓ Shipped 2026-05-18

Built Klaus from scratch: cloud-hosted, fully integrated, proactive where
hardcoded. 13 phases — Telegram bot, Gmail + Calendar + TickTick tools,
Cloud Run + CI/CD, Firestore + Pinecone memory, weather/Readwise/Garmin,
Five Fingers helper, proactive alerts, morning briefing, Notion, two chat
ingestion pipelines.

Detail: see `.planning/MILESTONES.md § v1.0`.

---

## Backlog

(none recorded)

---

## Next Milestone

v3.0 in progress. After close, candidates remain: deferred email-send,
Phase 19 hardening sweep items (see
`.planning/phases/18-autonomous-engine/deferred-items.md`), WhatsApp
outbound, multi-user, or new direction.
