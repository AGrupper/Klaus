# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## Milestones

- ✅ **v1.0 — Foundation & Integrations** — Phases 1–13 (shipped 2026-05-18)
- ✅ **v2.0 — Consciousness & Autonomy** — Phases 14–18 (shipped 2026-05-23)
- ✅ **v3.0 — Project Shifu** — Phases 19–20 (shipped 2026-06-02)
- ✅ **v4.0 — Specific Training & Nutrition Coaching** — Phases 21–25 (shipped 2026-06-08)
- ✅ **v5.0 — Klaus Hub** — Phases 26–30 (shipped 2026-07-09)
- [ ] **v6.0 — Klaus Becomes an Agent** — Phases 30.5, 31–35 (in progress)

---

## v6.0 — Klaus Becomes an Agent (Phases 30.5, 31–35) — In Progress

Rebuild Klaus from four independent, template-driven pipelines into one agent — a
capable model (`claude-sonnet-5`) with tools, ambient memory, standing directives,
and a single judgment cascade behind every proactive surface, guided by values
rather than behavior scripts. Klaus remembers involuntarily, perceives his full
situation (directives + recent conversation + reconciled training reality),
decides for himself what's worth saying — silence included — and can explain his
own decisions. Phase numbering follows the approved implementation plan's own
labels (decimal 30.5 is deliberate, precedent: v3.0's 19.1–19.3); previous
milestone (v5.0) ended at Phase 30.

**Phases:** 6 (30.5, 31, 32, 33, 34, 35) · **Requirements:** 37/37 mapped · Plan: `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` (+ review `~/.claude/plans/mellow-puzzling-nest.md`) · Architecture: `.planning/research/ARCHITECTURE.md`

Phase 0 (tick-brain → `openai/gpt-oss-120b`) shipped pre-milestone 2026-07-16
(commit `b784a1d`) and is not tracked as a roadmap phase.

## Phases

- [x] **Phase 30.5: Brain Upgrade (Sonnet 5)** — Smart brain moves to `claude-sonnet-5` with prompt caching, truthful cache-token metering, a decoupled tick-brain fallback shipped before the flip, a daily-spend tripwire, and a slimmed always-on prompt (completed 2026-07-19)
- [ ] **Phase 31: Standing Directives** — Amit's lasting behavioral wishes are captured, injected into every reasoning path with a Step-0 veto, listable/cancellable, and self-proposed from reflection's learning loop
- [ ] **Phase 32: Unified Situation (Ambient Memory)** — Ambient auto-recall, conversation continuity, and reconciled training reality reach every reasoning path as context-only signals that never defeat the free-tier cost gate
- [ ] **Phase 33: Occasion Cascade** — Nightly, morning, and weekly proactive messages become judgment-driven occasions through the shared 3-layer cascade, with silence a valid, explainable, and distinguishable-from-failure outcome
- [ ] **Phase 34: Write-Backs** — Calendar workout actions and chat-reported training changes mechanically and idempotently update the single training-reality source of truth
- [ ] **Phase 35: Hardening & Subtraction** — New judgment eval fixtures, a token-budget guard test, dead-code deletion, and updated invariants close the milestone

## Phase Details

### Phase 30.5: Brain Upgrade (Sonnet 5)
**Goal**: Klaus's smart brain runs on `claude-sonnet-5` with prompt caching active and cost metering that can be trusted — no silent fallback-cost inversion, no sampling-parameter errors, and a measurably lighter always-on prompt
**Depends on**: Nothing (first phase of v6.0; Phase 0 tick-brain migration already shipped pre-milestone)
**Requirements**: BRAIN-01, BRAIN-02, BRAIN-03, BRAIN-04, BRAIN-05, BRAIN-06, BRAIN-07
**Success Criteria** (what must be TRUE):
  1. Every conversation turn and every paid proactive compose is answered by `claude-sonnet-5`, and a forced Anthropic outage falls back cleanly to `gemini-3.5-flash`
  2. LLMUsage records cache-read/cache-write token counts with correctly computed cost, and Klaus's cost reporting is within ~10% of the Anthropic console
  3. A forced Groq failure in staging logs the tick-brain fallback as `gemini-3.5-flash` via the decoupled `TICK_BRAIN_FALLBACK_*` env — never `claude-sonnet-5` — verified deployed BEFORE the brain model flip
  4. When yesterday's total LLM cost exceeds `KLAUS_DAILY_COST_ALERT`, Klaus proactively tells Amit with a per-purpose cost breakdown and cache-hit rate
  5. Every Anthropic-backend call succeeds with no `temperature`/`top_p`/`top_k`/manual-`thinking` 400 errors, the always-on system prompt is measurably smaller (re-measured with the real Sonnet-5 tokenizer), and `UserProfileStore` reads are TTL-cached with no uncached Firestore read on every smart turn
**Plans**: 6 plans (4 waves)
- [x] 30.5-01-PLAN.md — Tick-brain fallback decoupling (TICK_BRAIN_FALLBACK_*), ship + live-verify before the flip (BRAIN-03)
- [x] 30.5-02-PLAN.md — Storage layer: LLMUsage cache/per-purpose cost + yesterday summary, UserProfileStore TTL cache, CostTripwireLog (BRAIN-02/04/07)
- [x] 30.5-03-PLAN.md — Anthropic prompt caching + cache-token metering + pricing + Sonnet-5 param/max_tokens compat (BRAIN-02/05)
- [x] 30.5-04-PLAN.md — Prompt slimming: compact SELF.md generator + light smart_agent.md de-prescription + count_tokens measurement (BRAIN-06)
- [x] 30.5-05-PLAN.md — Heartbeat daily-spend tripwire, once/day, brain-composed with template fallback (BRAIN-04)
- [x] 30.5-06-PLAN.md — Brain flip to claude-sonnet-5 + 3-tier fallback chain + D-12 disclosure + D-14 live checklist (BRAIN-01)

### Phase 31: Standing Directives
**Goal**: Amit can state a lasting wish about Klaus's behavior once and have it honored everywhere, indefinitely or until it expires/is cancelled, with conflicts surfaced and Klaus able to learn new directives from how Amit reacts to his own outreach
**Depends on**: Phase 30.5
**Requirements**: DIR-01, DIR-02, DIR-03, DIR-04, DIR-05, DIR-06, DIR-07
**Success Criteria** (what must be TRUE):
  1. Amit can state a lasting wish in chat (including "I already told you…") and Klaus stores it verbatim with origin + triggering-context quote, acknowledging it in one line
  2. A directive with a stated or implied end condition expires on it automatically; a directive with none persists until Amit cancels it — Klaus asks "until when?" only when genuinely unsure
  3. An active directive changes Klaus's behavior everywhere it's relevant — chat, tick triage (as a Step-0 veto above all other logic), Layer-2 compose, and follow-up compose — not just the surface where it was stated
  4. Amit can list and cancel standing directives from chat
  5. When a directive contradicts a baked-in persona routine, Klaus flags it, asks once which wins, and records the answer as a refined directive with a `superseded_by` link on the old one
  6. Nightly reflection reads the full day's conversation (not an empty 6h window) via `get_recent_window`, pairs each Klaus-initiated outreach with Amit's reaction, and may propose self-directives surfaced in the nightly message with a one-line veto
**Plans**: 6 plans (3 waves)
- [x] 31-01-PLAN.md — StandingDirectiveStore (verbatim capture, expiry fields, superseded_by chain, read-cached, never hard-delete) (DIR-02/05)
- [x] 31-02-PLAN.md — get_recent_window() + per-message ts on FirestoreConversationStore (fixes bug B3) (DIR-06)
- [ ] 31-03-PLAN.md — 3 brain-direct directive tools + shared render_standing_directives_block formatter + chat injection + capture rule (DIR-01/03/04/05)
- [ ] 31-04-PLAN.md — Autonomous injection: Step-0 STANDING ORDERS veto + Layer-2/follow-up compose + context-only gather (DIR-03)
- [ ] 31-05-PLAN.md — Legacy-cron veto (morning briefing + weekly review, D-21/D-22, skipped_by_directive) (DIR-03)
- [ ] 31-06-PLAN.md — Reflection learning loop (reaction pairing, self-directives, judged expiry, prune-flags) + nightly weaving (DIR-02/06/07)

### Phase 32: Unified Situation (Ambient Memory)
**Goal**: Klaus perceives his full situation on every reasoning path — relevant memories, conversation continuity, and reconciled training reality — without ever letting ordinary chat activity defeat the free-tier cost gate that is Klaus's entire cost model
**Depends on**: Phase 31 (`get_recent_window()` primitive)
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06, MEM-07
**Success Criteria** (what must be TRUE):
  1. Every chat turn auto-injects relevant Pinecone memories as a "Things you remember" block, best-effort with a short timeout — a slow or failed recall never blocks the turn
  2. After a 6h+ idle gap, a fresh "hey" is met with continuity (recent conversation tail prepended) instead of amnesia
  3. Amit can deliberately forget a memory via `forget_memory`, and reflection flags memories contradicted by newer facts — nothing decays automatically
  4. Tick triage and paid Layer-2 compose both see a reconciled `training_reality` window (planned vs. logged vs. Garmin/Hevy vs. calendar) — a session completed or moved earlier is never re-asked about
  5. A token-budget guard test confirms the maximal rendered triage prompt plus `max_tokens` fits Groq's verified per-request ceiling, and none of the new gathers (`conversation_tail`, `standing_directives`, `training_reality`, `location`) flip an otherwise-empty tick to non-empty
  6. Weather and travel-time gathers use Klaus's derived `current_location` (from calendar travel events + standing directives) — no more Tel Aviv forecasts delivered to Paris — and a local Groq daily token ledger alerts via heartbeat as usage nears the 200K TPD cap
**Plans**: TBD

### Phase 33: Occasion Cascade
**Goal**: Nightly review, morning briefing, and the Sunday weekly review stop being always-fire templates and become judgment-driven occasions through the same 3-layer cascade as the tick, with silence a valid, self-explainable outcome distinguishable from infra failure
**Depends on**: Phase 32 (context-only invariant + Groq token ledger must be safe before occasion traffic routes through triage)
**Requirements**: OCC-01, OCC-02, OCC-03, OCC-04, OCC-05, OCC-06, OCC-07
**Success Criteria** (what must be TRUE):
  1. The nightly review runs through the cascade and can be skipped by judgment (recorded as `skipped_by_judgment`); a total infra failure still sends the deterministic plain-text fallback, and the two are distinguishable in the logs
  2. The morning briefing runs through the cascade behind its existing Garmin wake-up anchor and 10:15 cutoff, writing the `structured` snapshot and `daily_note` only on an actual send
  3. The Sunday weekly review runs through the cascade as `occasion="weekly_review"`, retiring the last legacy composer (fold-in locked by user decision 2026-07-17)
  4. Occasions always get a free triage judgment regardless of the empty-signal gate, with `OutreachLog` topic keys `nightly:<date>` / `morning:<date>` / `weekly:<date>` and log entries written only after a successful send
  5. Layer 2 composes agentically within a bounded tool-call budget, and a directive-gated proactive calendar write checks for an existing planned row before creating a duplicate
  6. Amit can ask "why didn't you message me yesterday?" and `get_recent_decisions` returns a real answer from recent tick/occasion verdicts and reasoning
  7. `OCCASION_CASCADE` ships behind a flag with both the cascade and legacy composers live for a 3-4 day observation window before any legacy composer code is deleted
**Plans**: TBD

### Phase 34: Write-Backs
**Goal**: Calendar workout actions and chat-reported training changes durably and idempotently update `TrainingLogStore` — the thing Klaus was told stays true even if the model doesn't restate it later
**Depends on**: Phase 33 (occasion machinery supplies the date+slot dedup key for idempotency)
**Requirements**: WB-01, WB-02, WB-03, WB-04
**Success Criteria** (what must be TRUE):
  1. Creating a workout calendar event best-effort writes a planned `TrainingLogStore` row — the calendar create itself never fails because of it
  2. Moving or deleting a workout event updates the planned row symmetrically (a move merges a new-date row and marks the old one `skipped_reason="moved"`; a delete removes/marks the row)
  3. When Amit tells Klaus in chat that he did/moved/skipped a session, Klaus logs it before replying, and the chat-created row merges idempotently with later Garmin/Hevy completion data for the same `{date}_{slot}`
  4. The weekly review and the occasion cascade both read the same shared `training_reality` window instead of independently re-deriving split-vs-log guesses
**Plans**: TBD

### Phase 35: Hardening & Subtraction
**Goal**: Klaus's judgment is measurably tested against new fixtures, the codebase sheds retired pipelines and dead weight accumulated across the milestone, and the invariants this milestone introduces are documented for whoever builds on Klaus next
**Depends on**: Phase 34 (system stable enough to write fixtures against; Phase 33's observation window must have elapsed)
**Requirements**: HARD-01, HARD-02, HARD-03, HARD-04, HARD-05
**Success Criteria** (what must be TRUE):
  1. ≥6 new eval fixtures (vacation suppression, directive-expiry resumption, moved-session no-re-ask, nightly judgment-skip, nightly fold, follow-up cancelled by directive) pass via `scripts/eval_tick_brain.py`
  2. `core/proactive_alerts.py` (+ its route/prompt/tests), TickTick residue, the oversized `.venv.py314.bak/`, and `.claude/worktrees/` residue are gone from the repo, and the full suite still passes
  3. Chat-ingest (04:00) and chat-export-ingest (04:30) Cloud Scheduler jobs are paused, with the code kept and resumable anytime
  4. `PROJECT.md` Key Decisions records a worker-layer retirement verdict backed by measured post-Sonnet LLMUsage delegation volume
  5. `CLAUDE.md`/`TECHNICAL_PLAN.md`/`DEPLOYMENT.md` reflect the milestone's new invariants (directives-in-every-path, Groq per-request budget), and phase-pinned tool-registration tests are consolidated into one current-invariant test
**Plans**: TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 30.5. Brain Upgrade (Sonnet 5) | 6/6 | Complete    | 2026-07-19 |
| 31. Standing Directives | 2/6 | In Progress|  |
| 32. Unified Situation (Ambient Memory) | 0/? | Not started | - |
| 33. Occasion Cascade | 0/? | Not started | - |
| 34. Write-Backs | 0/? | Not started | - |
| 35. Hardening & Subtraction | 0/? | Not started | - |

---

## v5.0 — Klaus Hub (Phases 26–30) — Shipped 2026-07-09

A same-origin React + TypeScript + Vite PWA — the Klaus Hub — served by FastAPI
from the existing `klaus-agent` Cloud Run container, becoming Klaus's primary
interface: a Today timeline home screen (phone + desktop), full chat sharing the
Telegram Firestore conversation, native task and habit/supplement management
replacing TickTick, Web Push with a Telegram-mirror transition, and health pages
visualizing training, nutrition, and sleep from existing stores.

**Phases:** 5 (26–30) · **Plans:** 39 · **Tasks:** 75 · **Requirements:** 36/36 · Audit `passed`

| # | Phase | Outcome |
|---|-------|---------|
| 26 | Hub Shell | Vite/React/Tailwind PWA + multi-stage Dockerfile + mount-last SPA catch-all; Google Sign-In → session cookie; Today timeline + hub↔Telegram shared chat on a Cloud Tasks full-CPU path (HUB-01..05, CHAT-01..04, TIME-01..05/07/08) |
| 27 | Tasks | Native `TaskStore`/`TaskListStore` replacing TickTick — CRUD, 5 recurrence cadences, NL quick-add, soft-complete + undo, native Klaus tools + autonomous gather (TASK-01..07) |
| 28 | Habits & Supplements | `HabitStore` with one-tap check-offs, DST-safe streaks, contribution-grid history, autonomous adherence nudges, habits on timeline (HABIT-01..05, TIME-06) |
| 29 | Web Push & Transition | VAPID push fan-out behind a chat-visibility gate, injectManifest SW + IndexedDB unread badge, multi-device `PushSubscriptionStore`, runtime Telegram-mirror toggle (PUSH-01..04) |
| 30 | Health Pages | Training/nutrition/sleep-recovery visualizations on zero-dependency inline-SVG chart primitives with drill-downs, reading existing Firestore + Postgres stores (HLTH-01..03) |

Detail: see `.planning/milestones/v5.0-ROADMAP.md`,
`.planning/milestones/v5.0-REQUIREMENTS.md`, and
`.planning/milestones/v5.0-MILESTONE-AUDIT.md`.

---

## v4.0 — Specific Training & Nutrition Coaching (Phases 21–25) — Shipped 2026-06-08

Transformed Klaus from a qualitative coach into a genuinely expert, specific
hybrid-athlete coach — grounded in Amit's living blueprint + real Garmin/nutrition
data, driving facet-by-facet improvement across training blocks, proven by
end-of-block benchmarks and pace/strength projections toward the dated Oct/Nov goals.
Deployed to Cloud Run rev `klaus-agent-00091-4vz` (image `159cb1e`).

**Phases:** 5 (21–25) · **Plans:** 20 · **Requirements:** 20/20 · Suite 1058 passing · Audit `integration_ok`

| # | Phase | Outcome |
|---|-------|---------|
| 21 | Living Plan Ingestion | Blueprint → `UserProfileStore` structured fields (dated goals, weekly-split template, 6-slot fueling, supplements); `update_plan` tool — a living, critiqueable guide (PLAN-01/02/03) |
| 22 | Expert Coaching Knowledge + D-13 Release | `docs/COACHING_GUIDE.md` slim core on every brain call + `read_coaching_guide`; D-13 guard released under the Tier A/B data-presence contract — names real numbers, structural critique (COACH-01/02/06/07) |
| 23 | Block + Benchmark Tracking | `BlockStore` (date-range, auto transition) + `BenchmarkStore` (5-facet closed set), 4-block 16-week seed, 6 brain-direct tools, block-end benchmark state machine + HRV/ACWR gate in the 21:30 cron (BLOCK-01/02/03) |
| 24 | Strict Coaching Integration + Nutrition Accountability | `CoachingTopicStore` cross-cron dedup, macro/fueling-slot/supplement accountability, strict pushback + recovery-conflict framing, integrated morning block, session-quality at log time (COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04) |
| 25 | Progress Projection + Benchmark Trend Reporting | Deterministic `project_goal_progress` + `get_goal_projection` tool + dense Garmin pace history; on-track/behind trajectories in the Sunday weekly review (PROG-02) |

Detail: see `.planning/milestones/v4.0-ROADMAP.md`,
`.planning/milestones/v4.0-REQUIREMENTS.md`, and
`.planning/milestones/v4.0-MILESTONE-AUDIT.md`.

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

- ✅ **Fix `hours_since_contact`** — done 2026-06-12. The trigger was doubly
  dead: (1) the gather read a `TELEGRAM_USER_ID` env var that exists nowhere
  in the deployment, so it queried user 0 and returned null on all 823 live
  ticks — now reads the first entry of `TELEGRAM_ALLOWED_USER_IDS` like every
  other call site; (2) the Layer-0 empty gate ignored `hours_since_contact`
  entirely, so a silence-only day could never reach tick-brain even with
  data — long silence (≥ 8h, `_SILENCE_TRIGGER_HOURS`, same threshold as
  `_infer_trigger_type`) now counts as a salient signal. **Behavioral note
  for Amit:** during multi-day absences, every tick past 8h-since-contact now
  consults the (free) tick-brain, which may judge an occasional check-in
  worth sending — previously structurally impossible. If that feels chatty,
  tune the threshold or the triage prompt's silence guidance, and mint
  fixtures from the new outreach logs.
- ✅ **Tune `prompts/autonomous_triage.md` against the expanded eval** —
  done 2026-06-12. Restructured the triage prompt for qwen (hard
  followup-silence rule + ordered vetoes→signals→silence decision
  procedure) and fixed two request-shape bugs found during tuning
  (`TICK_BRAIN_MAX_TOKENS=2048` — the global 4096 budget made every Groq
  request 413 on the 6000-TPM per-request admission check and silently
  re-route to metered Gemini; `TICK_BRAIN_TEMPERATURE=0.6` — provider
  default ~1.0 made borderline verdicts flip run-to-run). Post-tuning:
  P 0.83–0.90 / R 0.73–0.91 / F1 0.80–0.87 over three runs, WARNING-8
  violations 0/6 (was 3/3), aged-overdue recall preserved. Full numbers in
  `evals/tick_brain/README.md § Baselines`.
- **Deploy the Groq tick-brain fix + tuned triage prompt (ready as of
  2026-06-12)** — ships together: the 2026-06-11 `core/tick_brain.py`
  fixes (model id `qwen/qwen3-32b`, `<think>` strip), the 2026-06-12
  request-shape fixes (max_tokens 2048, temperature 0.6 — without the
  max_tokens fix the Groq primary still never runs), and the tuned
  `prompts/autonomous_triage.md`. No Cloud Run env changes needed — all
  new knobs default correctly in code. Next-day verification: `llm_usage`
  should show `tick_autonomous_calls` > 0 for the first time ever.
