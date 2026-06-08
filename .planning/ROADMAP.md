# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## Milestones

- ✅ **v1.0 — Foundation & Integrations** — Phases 1–13 (shipped 2026-05-18)
- ✅ **v2.0 — Consciousness & Autonomy** — Phases 14–18 (shipped 2026-05-23)
- ✅ **v3.0 — Project Shifu** — Phases 19–20 (shipped 2026-06-02)
- 🚧 **v4.0 — Specific Training & Nutrition Coaching** — Phases 21–25 (in progress)

---

## v4.0 — Specific Training & Nutrition Coaching (Phases 21–25)

**Milestone Goal:** Transform Klaus from a qualitative coach into a genuinely expert, specific
hybrid-athlete coach — grounded in Amit's blueprint + real data, driving facet-by-facet
improvement in training blocks, proven by end-of-block benchmarks toward dated Oct/Nov goals.

**20 requirements** (PLAN-01..03, COACH-01..07, BLOCK-01..03, NUTR-01..03, PROG-01..04) across 5 phases.

## Phases

- [x] **Phase 21: Living Plan Ingestion** - Populate `UserProfileStore` with Amit's blueprint as structured fields (dated goals, weekly split, fueling timeline, supplements); add `update_plan` tool; gate that unblocks all downstream coaching specificity (completed 2026-06-04)
- [x] **Phase 22: Expert Coaching Knowledge + D-13 Release** - Author `docs/COACHING_GUIDE.md`, wire it into every coaching prompt, replace the D-13 qualitative guard with the Tier A / Tier B data-presence contract; Klaus starts naming real numbers (completed 2026-06-05)
- [x] **Phase 23: Block + Benchmark Tracking** - `BlockStore` + `BenchmarkStore` Firestore stores, 7 brain-direct tools, block state surfaced in existing crons, end-of-block benchmark trigger logic (completed 2026-06-06)
- [x] **Phase 24: Strict Coaching Integration + Nutrition Accountability** - Fold expert, specific coaching into all existing crons (morning briefing, evening check-in, weekly review), add cross-cron dedup gate, add nutrition/supplement accountability (completed 2026-06-06)
- [ ] **Phase 25: Progress Projection + Benchmark Trend Reporting** - Pace-to-deadline trend projection against Oct/Nov goals; per-facet benchmark improvement surfaced in weekly review

## Phase Details

### Phase 21: Living Plan Ingestion
**Goal**: Amit's Hybrid Athlete blueprint lives in `UserProfileStore` as structured fields that every cron and brain-direct tool can read; the plan is encoded as a flexible weekly template (volume/trend targets, not day-by-day prescriptions); Amit can update it at any time via the `update_plan` tool
**Depends on**: Nothing (first v4.0 phase)
**Requirements**: PLAN-01, PLAN-02, PLAN-03
**Success Criteria** (what must be TRUE):
  1. `UserProfileStore.load()` returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, and `plan_start_date` — not a raw markdown blob
  2. The weekly split is stored as a template with session priorities and block-level volume targets, not per-session boolean attendance flags (asking "did Klaus nag about a single missed session?" is the regression test)
  3. Amit can say "update my bench goal to 105kg" or "change Thursday to rest day" and Klaus reasons against the updated plan on the very next turn
  4. The `training_profile` section in the smart agent prompt reflects blueprint fields and frames them as a coaching reference guide, not a rigid contract
**Plans**: 4 plans
- [x] 21-01-PLAN.md — Expand UserProfileStore schema to v4.0 structured fields (dated_goals, weekly_split, nutrition_targets, supplement_schedule, fueling_timeline, plan_start_date)
- [x] 21-02-PLAN.md — update_plan tool + extended update schema + JSON-safe get_training_profile handler
- [x] 21-03-PLAN.md — scripts/ingest_blueprint.py: idempotent blueprint → structured Firestore ingest (dry-run/force)
- [x] 21-04-PLAN.md — Coaching-reference prose rendering + prompt reframe + v3.0 cron-regression check

### Phase 22: Expert Coaching Knowledge + D-13 Release
**Goal**: Klaus carries curated, source-tier-tagged hybrid-athlete coaching knowledge in his reasoning substrate; the D-13 no-fabrication guard is replaced with a two-tier data-presence contract (Tier A = blueprint targets, always citable; Tier B = measured results, citable only within a recency window); coaching output names specific sessions, loads, and rationales instead of generic advice; Klaus critiques suboptimal plan elements rather than treating the blueprint as gospel
**Depends on**: Phase 21
**Requirements**: COACH-01, COACH-06, COACH-02, COACH-07
**Success Criteria** (what must be TRUE):
  1. A coaching query when `TrainingLogStore` has no recent bench data returns "I don't have a recent bench logged, Sir" — not an invented number; blueprint goal is cited as "your target" not "your current performance"
  2. The morning briefing and evening alert name the specific scheduled session and load/pace target from the blueprint when producing a coaching point
  3. When asked about a training session, Klaus names the session type, the plan load, and the rationale — never "do your strength session" as a complete coaching message
  4. Klaus identifies at least one structural element of the blueprint or Amit's habits as worth questioning (e.g. protein target, supplement timing), explains the reasoning, and recommends a specific alternative without silently rewriting the plan
**Plans**: 4 plans
- [x] 22-01-PLAN.md — Author docs/COACHING_GUIDE.md (slim core + 10 anchored deep sections, applied to Amit's blueprint)
- [x] 22-02-PLAN.md — Slim-core loader + render injection + brain-direct read_coaching_guide tool (4-site) + Wave-0 tests
- [x] 22-03-PLAN.md — Wire {coaching_guide} into morning briefing / evening alert / autonomous crons (compose-time injection + cost bias)
- [x] 22-04-PLAN.md — smart_agent.md: D-13 guard release → Tier A/B recency contract + specificity bar + critique posture (human-verify gate)
**UI hint**: no

### Phase 23: Block + Benchmark Tracking
**Goal**: Klaus tracks the current training block (week number, phase, dates) and surfaces that context in all coaching messages; at block end he prompts a standardized benchmark test session with a biometric validity gate; results are recorded per-facet and compared across blocks to show improvement over time
**Depends on**: Phase 21
**Requirements**: BLOCK-01, BLOCK-02, BLOCK-03
**Success Criteria** (what must be TRUE):
  1. `BlockStore.get_current()` returns the active block with the correct week number derived from `plan_start_date` (2026-06-21); cron messages include "Week N of 16, [phase name]" framing
  2. The end-of-block benchmark prompt fires within 3 days of stored `block_end_date` via the existing 21:30 cron — no new cron job created
  3. The benchmark prompt includes a biometric validity gate: it defers (with explanation) when HRV is below 70% of 7-day baseline or ACWR is above 1.2
  4. Klaus records a benchmark result via `log_benchmark` and can surface a facet's history across blocks (e.g., "bench press: 80kg Block 1 → 85kg Block 2")
**Plans**: 4 plans
- [x] 23-01-PLAN.md — BlockStore + BenchmarkStore + UserProfileStore.current_block_id + idempotent seed script + Wave-0 store tests (foundation)
- [x] 23-02-PLAN.md — 6 brain-direct tools (get_plan, get_block_status, log_benchmark, get_benchmark_history, start_block, end_block) + registration tests
- [x] 23-03-PLAN.md — benchmark_due state machine + HRV/ACWR validity gate + re-prompt/stale-window in the 21:30 cron + proactive_alert.md rendering
- [x] 23-04-PLAN.md — Block-state gather + "Week N of 16" framing in morning briefing & Sunday weekly review (+ both prompt files)

### Phase 24: Strict Coaching Integration + Nutrition Accountability
**Goal**: Expert, specific coaching is folded into every existing coaching touchpoint (morning briefing, 21:30 training check-in + evening alert, Sunday weekly review, and chat); coaching is proactive and reactive; a cross-cron dedup gate ensures the same topic fires at most once per day across all crons; nutrition macro adherence and fueling-slot accountability and supplement timing are part of the 21:30 check-in; session quality rating is captured at log time
**Depends on**: Phase 22, Phase 23
**Requirements**: COACH-03, COACH-04, COACH-05, NUTR-01, NUTR-02, NUTR-03, PROG-01, PROG-03, PROG-04
**Success Criteria** (what must be TRUE):
  1. A skipped session triggers pushback that names the session, the volume deficit in concrete units (km or sets), and the consequence for the goal timeline — no softening language
  2. A recovery-vs-plan conflict produces: biometric fact with number + plan conflict + single ranked recommendation + explicit "your call, Sir" — never dictating and never hedging
  3. The same coaching topic (e.g., protein miss, skipped session) does not appear in both the morning briefing and the evening check-in on the same day
  4. The 21:30 check-in flags structural fueling-slot misses (e.g., missed post-AM-run reload) using `MealStore` timestamps mapped to the 6 blueprint slots — not marginal macro adjustments
  5. The morning briefing frames today's named session, recovery state, and relevant fueling reminder as one integrated block
  6. The Sunday weekly review reports per-facet progress (strength top-set trend, threshold volume vs target, ACWR) with block-relative framing, and surfaces session quality trends from the annotated log
**Plans**: 5 plans
- [x] 24-01-PLAN.md — CoachingTopicStore dedup gate + derived session-quality field (foundation: COACH-05, PROG-04)
- [x] 24-02-PLAN.md — Nutrition pure helpers: macro-gap, meal→fueling-slot mapping, slot-miss + supplement riders (NUTR-01/02/03)
- [x] 24-03-PLAN.md — Folded fixes: read_coaching_guide WR-02 hardening + smart-loop double-send cap/fallback
- [x] 24-04-PLAN.md — 21:30 cron: nutrition gather + cross-cron dedup gate + strict-pushback/recovery prompts (proactive_alert.md, smart_agent.md)
- [x] 24-05-PLAN.md — Morning briefing integrated block + Sunday weekly review per-facet + quality trend (+ both prompts, dedup wiring)

### Phase 25: Progress Projection + Benchmark Trend Reporting
**Goal**: Klaus projects strength and pace trends against the dated Oct/Nov goals and reports on-track or behind; per-facet benchmark results are surfaced as improvement trajectories in the Sunday weekly review; this is the highest dependency-chain feature in the milestone
**Depends on**: Phase 23, Phase 24
**Requirements**: PROG-02
**Success Criteria** (what must be TRUE):
  1. Klaus answers "am I on track for my October bench target?" by computing a trend from `TrainingLogStore` top-set history (or `BenchmarkStore` results) and projecting it to the deadline — not by citing the goal alone
  2. The Sunday weekly review surfaces a pace-to-deadline status for at least one goal facet: "current trend puts you at [X] by [date] — on track / N weeks behind"
  3. The projection explicitly distinguishes blueprint target (Tier A) from current measured trend (Tier B) — no fabricated convergence claims
**Plans**: 3 plans
- [x] 25-01-PLAN.md — Deterministic projection helper core/projection.py + unit tests (Wave 1 foundation: pure-function trend/projection, direction-aware, today_iso injected)
- [x] 25-02-PLAN.md — Reactive get_goal_projection brain-direct tool in core/tools.py + smart_agent.md projection permission (Wave 2)
- [ ] 25-03-PLAN.md — Sunday weekly-review projection block + COACH-05 dedup + weekly_training_review.md fence lift (Wave 2)

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 21. Living Plan Ingestion | 4/4 | Complete    | 2026-06-04 |
| 22. Expert Coaching Knowledge + D-13 Release | 4/4 | Complete    | 2026-06-05 |
| 23. Block + Benchmark Tracking | 4/4 | Complete    | 2026-06-06 |
| 24. Strict Coaching Integration + Nutrition Accountability | 5/5 | Complete   | 2026-06-06 |
| 25. Progress Projection + Benchmark Trend Reporting | 2/3 | In Progress|  |

---

## v3.0 — Project Shifu (Phases 19–20) — Shipped 2026-06-02

Gave Klaus athletic-coaching capability: he reads his own 3-year Garmin training
history from Postgres, ingests Lifesum nutrition via the iOS HealthKit bridge,
holds the user accountable to logged sessions with an evidence-first 21:30
training check-in, surfaces recovery state (ACWR / HRV / sleep) in the morning
briefing and evening alert, and sends a Sunday weekly training review.
Plumbing + accountability loop — **personalized targets/prescriptions are
deferred to v4.0** (the `UserProfileStore` scaffold stays empty until then, so
coaching is qualitative under the D-13 no-fabrication guard).

**Phases:** 5 (19, 19.1, 19.2, 19.3, 20) · **Plans:** 17 · **Tasks:** 27 · Verified 19/19 + live UAT

| # | Phase | Outcome |
|---|-------|---------|
| 19 | Training Awareness & Nutrition Coaching | Postgres schema + 3yr Garmin backfill, `UserProfileStore` scaffold, ACWR/training-status/activities reads, `MealStore`, mid-day nutrition coaching + morning recap |
| 19.1 | HealthKit Nutrition Bridge | Lifesum → HealthKit → `/cron/healthkit-sync` → `MealStore` (server-side aggregation, idempotent); live UAT 6/6 |
| 19.2 | Fiber Through Reasoning Layer *(inserted)* | `DietaryFiber_g` threaded through normalizer → `MealStore` totals → `meal_audit` + briefings |
| 19.3 | Meal Read Paths → MealStore *(inserted)* | Both meal read paths repointed off the dead Google Fit source to `MealStore` |
| 20 | Accountability Crons & Recovery Briefing | `TrainingLogStore` + `PendingPromptStore`, evidence-first check-in (inline keyboards, Garmin-RPE-aware) folded into 21:30 cron, `recovery_concern` in briefing + alert, Sunday weekly review, `bootstrap_shifu_crons.sh` |

Detail: see `.planning/milestones/v3.0-ROADMAP.md` and
`.planning/milestones/v3.0-REQUIREMENTS.md`.

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) — Shipped 2026-05-23

Made Klaus self-aware, judgment-driven, cost-transparent: every LLM call
metered, free always-on tick-brain, self-inspect tools, auto-generated SELF.md
manifest + mutable self_state, daily reflection cron, and the autonomous
engine (`*/20 7-21` triage + compose pipeline with repeat-suppression +
eval harness).

**Phases:** 5 · **Plans:** 24 · **Requirements:** 41/41

Detail: see `.planning/milestones/v2.0-ROADMAP.md` and
`.planning/milestones/v2.0-REQUIREMENTS.md`.

---

## v1.0 — Foundation & Integrations (Phases 1–13) — Shipped 2026-05-18

Built Klaus from scratch: cloud-hosted, fully integrated, proactive where
hardcoded. 13 phases — Telegram bot, Gmail + Calendar + TickTick tools,
Cloud Run + CI/CD, Firestore + Pinecone memory, weather/Readwise/Garmin,
Five Fingers helper, proactive alerts, morning briefing, Notion, two chat
ingestion pipelines.

Detail: see `.planning/MILESTONES.md § v1.0`.

---

## Backlog

(none recorded)
