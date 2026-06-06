# Klaus — Personal Hybrid Agent

## What This Is

Klaus is a cloud-hosted personal AI agent for Amit that manages scheduling, task management, proactive alerts, and daily workflows. It uses a dual-model architecture (Gemini 3 Flash as the brain, Gemini 2.5 Flash as the worker) with Telegram as the primary interface, integrated with Gmail, Google Calendar, TickTick, Notion, Garmin, and a vector memory store (Pinecone). No local Mac dependency — fully Cloud Run native.

## Core Value

Klaus should act as a genuinely intelligent, proactive companion that surfaces the right thing at the right time — while knowing exactly what he is and what he can do.

## Current State

**Shipped:** v3.0 — Project Shifu (2026-06-02). Klaus now has athletic-coaching
capability: he reads his own 3-year Garmin history + Lifesum nutrition (via the iOS
HealthKit bridge → `MealStore`), runs an evidence-first 21:30 training check-in with
inline-keyboard logging, surfaces recovery state (ACWR / HRV / sleep) in the morning
briefing and evening alert, and sends a Sunday weekly training review. The
accountability **loop** is live and verified end-to-end (19/19 + live UAT).

**v4.0 in progress (3/5 phases):** Phase 21 ingested Amit's Hybrid Athlete blueprint
into `UserProfileStore` as a structured living guide (editable via `update_plan`). Phase 22
made Klaus a genuinely *expert, specific* coach: curated source-tier-tagged knowledge
(`docs/COACHING_GUIDE.md`) on every brain call + cron, and **the D-13 no-fabrication guard
is released** — replaced by a recency-windowed Tier A/B data-presence contract, so Klaus now
names real numbers, prescribes specific session/load/rationale, and volunteers structural
critique (recommend-not-rewrite). Verified live on Telegram 2026-06-05. Phase 23 added
**block + benchmark tracking**: `BlockStore` (date-range resolution, automatic inter-block
transition) + `BenchmarkStore` (5-facet closed set) Firestore stores, an idempotent 4-block
16-week seed, 6 new brain-direct tools (`get_plan`/`get_block_status`/`log_benchmark`/
`get_benchmark_history`/`start_block`/`end_block`), "Week N of 16" framing in the morning
briefing + Sunday weekly review, and an end-of-block benchmark trigger in the existing 21:30
cron behind an HRV/ACWR validity gate (window-open / deferred / stale). Verified 4/4
2026-06-06. Next: strict coaching integration + nutrition accountability (Phase 24).

**Milestones shipped:** v1.0 Foundation (2026-05-18) · v2.0 Consciousness & Autonomy
(2026-05-23) · v3.0 Project Shifu (2026-06-02). See `.planning/MILESTONES.md`.

## Current Milestone: v4.0 — Specific Training & Nutrition Coaching

**Goal:** Transform Klaus from a *qualitative* coach into a genuinely *expert, specific*
hybrid-athlete coach — grounded in Amit's blueprint + real data, driving facet-by-facet
improvement in training blocks, proven by end-of-block benchmarks toward dated goals.

**Target features:**
- Ingest Amit's Hybrid Athlete blueprint → populate `UserProfileStore` as a *living guide*:
  dated goals (Oct: 100kg bench / 120kg squat / 1:25 HM; Nov: 125 push-ups / 35 pull-ups /
  9:30 3k / 55s 400m), the facets/priorities, the AM/PM weekly split, the nutrition framework
  (150g protein / 350g carbs + 6-part fueling timeline), and the supplement schedule.
- Curated **expert coaching knowledge** (concurrent strength/endurance, interference effect,
  periodization, how to execute the specific sessions, fueling science) baked into Klaus's
  coaching reasoning so it is genuinely expert, not generic.
- Release the **D-13 "no invented numbers" guard** — Klaus names real numbers grounded in
  data: current lifts/paces, trends, macro & supplement adherence.
- **Training blocks + benchmark testing** — track the current block, prompt a benchmark
  session at block end, record results, compare across blocks to show per-facet improvement.
- **Specific, strict, proactive + reactive coaching** folded into the existing crons
  (morning briefing, evening check-in, weekly review) + chat: names specific sessions,
  pushes Amit to train hard, critiques off-plan training/nutrition/supplements, flags
  recovery-vs-plan conflicts (Amit decides), holds macro accountability.
- **Progress toward dated goals** — trend-based per-facet improvement + pace-to-deadline
  awareness against the Oct/Nov targets.

**Key context:**
- Goals are dated but the philosophy is *facet-mastery, not goal-cramming*. Testing is at
  block ends + the deadlines, not periodic.
- On recovery-vs-plan conflicts Klaus *advises, Amit decides* (not coach-override).
- Builds on v3.0 plumbing: `UserProfileStore` scaffold, `MealStore`, `TrainingLogStore`,
  Garmin/ACWR, recovery crons.

## Requirements

### Validated

- ✓ Telegram bot interface (webhook, Cloud Run) — Phase 1
- ✓ Dual-model LLM abstraction (`llm_client.py`) — Phase 2
- ✓ Gmail + Google Calendar tools — Phase 3
- ✓ TickTick task tool (reminder + deadline) — Phase 4
- ✓ Cloud Run deployment with CI/CD + Secret Manager — Phase 5
- ✓ Conversation persistence (Firestore) + vector memory (Pinecone RAG) — Phase 6
- ✓ External connections: weather, Readwise, Garmin — Phase 7
- ✓ Five Fingers practice helper (3 cron flows) — Phase 8
- ✓ Proactive evening alerts (21:30 nightly) — Phase 9
- ✓ Morning briefing (Garmin-anchored, */10 cron) — Phase 10
- ✓ Notion integration (5 tools) — Phase 11
- ✓ Claude Code chat-log ingestion → Pinecone + Notion — Phase 12
- ✓ Multi-source AI chat export ingestion (Claude.ai, ChatGPT, Gemini) — Phase 13
- ✓ Every LLM call is cost-metered and stored (Phase 14)
- ✓ Free tick-brain component exists and upgrades the heartbeat (Phase 14)
- ✓ Klaus can read and search his own deployed source files — `list_own_files`, `read_own_source`, `search_own_source` brain-direct tools with secret denylist (Phase 15)
- ✓ SELF.md manifest auto-generated; injected into every conversation (Phase 16)
- ✓ `get_self_status` tool returns uptime, cost, heartbeat status (Phase 16)
- ✓ SelfStateStore persists identity state across 6h conversation resets (Phase 16)
- ✓ Heartbeat weekly SHA check flags stale SELF.md; CI regenerates on every deploy (Phase 16)
- ✓ Daily reflection cron writes journal entries + updates self-state (Phase 17)
- ✓ Autonomous tick engine fires every 20 min, 7-21, with judgment + repeat-suppression (Phase 18)
- ✓ Judgment eval harness scores tick-brain on labeled fixtures (Phase 18)
- ✓ Training/recovery data layer: Postgres schema + 3yr Garmin backfill, ACWR, `MealStore` — v3.0 (Phase 19)
- ✓ iOS HealthKit nutrition bridge (Lifesum → `MealStore`), fiber threaded + meal reads repointed off Google Fit — v3.0 (Phases 19.1–19.3)
- ✓ Evidence-first training check-in + `TrainingLogStore` (inline-keyboard logging, folded into 21:30 cron) — v3.0 (Phase 20)
- ✓ Recovery-aware morning briefing + evening alert (`compute_recovery_concern`, no-fabrication guard) — v3.0 (Phase 20)
- ✓ Sunday weekly training review cron (brain-composed scorecard) — v3.0 (Phase 20)
- ✓ Workouts Klaus creates route to the `Training` calendar; `get_training_history` JSON-safe — v3.0 (post-ship UAT fixes)
- ✓ Blueprint ingested as a *living guide* in `UserProfileStore` (structured dated_goals / weekly_split / nutrition_targets / supplement_schedule / fueling_timeline / plan_start_date); `update_plan` tool edits it on the next turn — v4.0 (Phase 21) — PLAN-01/02/03
- ✓ Curated expert coaching knowledge (`docs/COACHING_GUIDE.md`: slim core on every brain call + 10 anchored deep sections via brain-direct `read_coaching_guide`) wired into every coaching prompt + cron — v4.0 (Phase 22) — COACH-01
- ✓ D-13 no-fabrication guard released → recency-windowed Tier A/B data-presence contract; Klaus names real numbers, specific session/load/rationale, and volunteers structural critique (recommend-not-rewrite) — verified live 2026-06-05 — v4.0 (Phase 22) — COACH-02/06/07
- ✓ Block + benchmark tracking: `BlockStore` (date-range resolution, auto inter-block transition) + `BenchmarkStore` (5-facet closed set), 4-block 16-week seed, 6 brain-direct tools, "Week N of 16" framing in morning briefing + weekly review, end-of-block benchmark trigger in the 21:30 cron behind an HRV/ACWR validity gate (window-open/deferred/stale) — verified 4/4 2026-06-06 — v4.0 (Phase 23) — BLOCK-01/02/03

### Active (v4.0 — Specific Training & Nutrition Coaching)

To be defined at requirements scoping (this milestone). Headline direction: ingest the
blueprint as a living guide, give Klaus curated expert coaching knowledge, release the
D-13 guard for data-grounded specificity, manage training blocks with end-of-block
benchmark testing, and make coaching strict/specific (proactive + reactive) across
training, nutrition, and supplements.

**Deferred (carried forward):**
- Live-staging verification of v2.0 SC-1/SC-2/SC-4 (see STATE.md § Deferred Items)
- Stale Phase 19 verification/UAT sign-off paperwork (functionality verified live)
- Recurring "daily review" skill (check-in persistence); `MealAuditStore` (persisted nutrition critique)

### Out of Scope

- Email sending — Gmail stays read-only this milestone; clean fast-follow
- WhatsApp autonomous outbound — user-initiated only (wa.me links)
- Multi-user support — single user (Amit) throughout
- Spend caps — cost is measured, never enforced (explicit user choice)

## Context

- **Stack:** Python 3.11 (prod Dockerfile) / 3.13 (local venv), Cloud Run, Firestore, Pinecone, Postgres, FastAPI, Telegram Bot API
- **Brain model:** `gemini-3.5-flash` (Gemini AI Studio)
- **Worker model:** `deepseek-v4-flash` (OpenAI-compat, DeepSeek API)
- **Fallback:** `claude-haiku-4-5` (Anthropic, inline on brain failure)
- **Tick-brain:** `qwen3-32b` (Groq, free) with `gemini-3.5-flash` fallback
- **Embeddings:** `gemini-embedding-2` via AI Studio (NOT Vertex — AI Studio only)
- **Cron jobs (8):** heartbeat (hourly), proactive-alerts (21:30, now also runs the training check-in), morning-briefing-tick (*/10 6-10), chat-ingest (04:00), chat-export-ingest (04:30), klaus-reflect (22:00), klaus-autonomous-tick (*/20 7-21), klaus-weekly-training-review (Sun 10:00). Plus push-driven `/cron/healthkit-sync`. *(Five Fingers crons removed; Google Fit deprecated — commit `91e218e`.)*
- **Pinecone kinds:** `{"fact","chunk","chat","self"}`
- **Test env note:** full `pytest tests/` segfaults in one process (grpc/protobuf GC, 3.13 + 3.14) — verify per-file. See `feedback_python_version` + `feedback_firestore_timestamp_json` memories.

## Constraints

- **Cloud-only:** No local Mac runtime dependency
- **Outbound:** Telegram to Amit only; no autonomous WhatsApp/email send
- **Single user:** No multi-tenant support
- **Cost model:** Measure everything, cap nothing (user preference)
- **Quiet hours:** Autonomous outreach window `7-21` (cron); reflection at ~22:00

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Gemini 3 Flash as brain (not Claude) | Lower cost, better tool use at scale | ✓ Good |
| Groq/Qwen3-32B for tick-brain | Free tier, fast, doesn't train on data, OpenAI-compat | ✓ Implemented Phase 14 |
| No spend cap | "I want him to be able to do whatever he wants" — explicit user choice | ✓ Implemented Phase 14 |
| Outbound Telegram-only | Clean scope; email send is a fast-follow | ✓ Good |
| `kind="self"` in Pinecone | Journal entries need their own namespace distinct from facts/chat | ✓ Implemented Phase 17 |
| Tick every 20 min, 7-21 | ≈42 ticks/day; balances proactivity with quiet hours | ✓ Implemented Phase 18 |
| HealthKit bridge over Google Fit (iOS) | Lifesum writes to HealthKit on iPhone; Google Fit returns nothing | ✓ Good — v3.0 (19.1) |
| Training check-in folds into 21:30 cron (D-09, no separate job) | Avoids a redundant scheduler job; runs before the dedup gate so retries aren't blocked | ✓ Good — v3.0 |
| No invented numbers until profile populated (D-13) | Honest coaching with an empty profile; releases at v4.0 | ✓ Good — v3.0 |
| No `MealAuditStore` (live `MealStore` 7-day totals, D-21) | Avoid premature persistence; brain critiques at read time | ✓ Good — v3.0 (revisit if nutrition history reporting matters) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-06 — Phase 23 (Block + Benchmark Tracking) complete; 3/5 v4.0 phases done.*
