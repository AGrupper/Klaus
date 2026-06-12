# Klaus — Personal Hybrid Agent

## What This Is

Klaus is a cloud-hosted personal AI agent for Amit that manages scheduling, task management, proactive alerts, daily workflows, and — as of v4.0 — acts as a genuinely expert hybrid-athlete coach (training-block periodization, end-of-block benchmarks, dated-goal projection, and nutrition/supplement accountability grounded in Amit's living blueprint + real Garmin/nutrition data). It uses a dual-model architecture (`gemini-3.5-flash` as the brain, `deepseek-v4-flash` as the worker, `claude-haiku-4-5` inline fallback, free `qwen3-32b` tick-brain) with Telegram as the primary interface, integrated with Gmail, Google Calendar, TickTick, Notion, Garmin, Postgres, and a vector memory store (Pinecone). No local Mac dependency — fully Cloud Run native.

## Core Value

Klaus should act as a genuinely intelligent, proactive companion that surfaces the right thing at the right time — while knowing exactly what he is and what he can do.

## Current State

**Shipped:** v4.0 — Specific Training & Nutrition Coaching (2026-06-08, Cloud Run rev
`klaus-agent-00091-4vz`, image `159cb1e`). Klaus is now a genuinely expert, specific
hybrid-athlete coach. Across 5 phases (21–25) he: ingests Amit's Hybrid Athlete blueprint
into `UserProfileStore` as a structured **living guide** (editable via `update_plan`);
carries curated expert coaching knowledge (`docs/COACHING_GUIDE.md` slim core on every brain
call + `read_coaching_guide` deep sections); **released the D-13 no-fabrication guard** under
a recency-windowed Tier A/B data-presence contract (names real numbers, specific
session/load/rationale, structural critique); tracks **training blocks + benchmarks**
(`BlockStore` date-range resolution + `BenchmarkStore` 5-facet closed set, end-of-block
benchmark state machine behind an HRV/ACWR gate); folds **strict, nutrition-accountable**
coaching into all crons (cross-cron dedup via `CoachingTopicStore`, macro/fueling-slot/
supplement accountability, derived session quality); and **projects** strength/pace trends to
the dated Oct/Nov deadlines (deterministic `core/projection.py` + `get_goal_projection` tool +
dense Garmin pace history, surfaced in the Sunday weekly review as on-track / N-weeks-behind).
20/20 requirements satisfied · suite 1058 passing · audit `integration_ok` · Phase 25 secured
16/16 threats + all 10 code-review findings fixed pre-deploy.

**Milestones shipped:** v1.0 Foundation (2026-05-18) · v2.0 Consciousness & Autonomy
(2026-05-23) · v3.0 Project Shifu (2026-06-02) · v4.0 Specific Training & Nutrition Coaching
(2026-06-08). See `.planning/MILESTONES.md`.

## Current Milestone: v5.0 Klaus Hub

**Goal:** A web PWA (served from the klaus-agent Cloud Run service) that becomes Klaus's
primary interface — replacing Telegram for chat, TickTick for tasks, and the habit app —
with a Today timeline as the home screen on phone and desktop.

**Target features:**
- Hub shell: React + TypeScript PWA served by FastAPI, Google Sign-In (Amit only), Today
  timeline composing calendar + meals + habits + training plan + Garmin stats + weather
- Full Klaus chat sharing the Telegram Firestore conversation (same Cloud Tasks full-CPU
  path); polling while open, Web Push when closed
- Native tasks: `TaskStore` + Klaus tool swap (TickTick → native) + one-time TickTick import
- Habits + supplements: `HabitStore` with dose field, daily check-offs, streaks,
  autonomous-tick adherence awareness
- Web Push (VAPID) with Telegram mirror flag — hybrid transition, eventually retire Telegram
- Health pages: training history, nutrition detail, sleep trends

**Design spec:** `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` (approved
2026-06-13; layout locked via visual mockups — desktop: sidebar + timeline + glance rail +
docked collapsible chat; phone: bottom tabs with Klaus center tab). Nutrition stays
display-only (Lifesum → HealthKit pipeline unchanged). Music/PC-control widgets deferred.

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
- ✓ Strict coaching integration + nutrition accountability: `CoachingTopicStore` cross-cron dedup (one topic/day across morning briefing + 21:30 + weekly review), macro adherence + 6-slot fueling + supplement accountability in the 21:30 check-in, strict skip-pushback + recovery-conflict framing ("your call, Sir"), integrated morning briefing block, and session-quality captured at log time — verified 6/6 + live 2026-06-07 — v4.0 (Phase 24) — COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04
- ✓ Progress projection toward dated goals: deterministic pure-function `core/projection.py` (stdlib least-squares trend → on-track / N-weeks-behind, `today_iso`-only, never raises, direction-normalized `behind_by`), reactive `get_goal_projection` brain tool (D-04 dense Garmin pace history vs sparse `BenchmarkStore`), and a Sunday weekly-review projection block with the Phase-24 fence lifted — Tier A target vs Tier B measured trend always distinguished — verified 3/3 2026-06-08, all 10 code-review findings fixed pre-deploy — v4.0 (Phase 25) — PROG-02

### Active

v5.0 Klaus Hub — requirements being defined (see REQUIREMENTS.md once written).

**Deferred (carried forward):**
- Live-staging verification of v2.0 SC-1/SC-2/SC-4 (see STATE.md § Deferred Items)
- Recurring "daily review" skill (check-in persistence); `MealAuditStore` (persisted nutrition critique)
- Nyquist formal validation artifacts for v4.0 phases (P21 missing VALIDATION.md; P23/P25 drafts `nyquist_compliant: false`) — test suites robust; close retroactively via `/gsd-validate-phase` if desired
- One live re-observation of the coaching double-send fix (data-heavy query → single message); accepted design notes WR-01 (cron `plan_start_date` hardcode, D-03) and WR-02 (`fueling_timeline` not gathered into crons, D-11)

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
| No invented numbers until profile populated (D-13) | Honest coaching with an empty profile; releases at v4.0 | ✓ Released v4.0 (Phase 22) → Tier A/B contract |
| No `MealAuditStore` (live `MealStore` 7-day totals, D-21) | Avoid premature persistence; brain critiques at read time | ✓ Good — v3.0 (revisit if nutrition history reporting matters) |
| Coaching knowledge = prompt-injected `docs/COACHING_GUIDE.md`, NOT Pinecone RAG | ~5k-token slim core always-on, zero retrieval latency; deep sections via `read_coaching_guide` | ✓ Good — v4.0 (Phase 22) |
| D-13 release is prompt-only Tier A/B data-presence contract | Tier A blueprint targets always citable; Tier B measured numbers only within a recency window — no fabrication | ✓ Good — v4.0 (Phase 22), verified live |
| Block/benchmark as Firestore stores with date-range `get_current()` | `BlockStore`/`BenchmarkStore` follow the `TrainingLogStore` pattern; date-range resolution auto-handles inter-block transitions | ✓ Good — v4.0 (Phase 23) |
| Cross-cron dedup via `CoachingTopicStore` (write-after-send) | One topic/day across all crons; topic written only after `send_and_inject` succeeds (D-10) | ✓ Good — v4.0 (Phase 24) |
| Projection is a deterministic pure function (`core/projection.py`), brain never computes | LSQ trend from real history only; brain frames, never invents the number — protects the projection trust surface | ✓ Good — v4.0 (Phase 25) |
| Blueprint is a critiqueable guide, not gospel (COACH-07); Amit adopts via `update_plan` | Klaus recommends structural changes, never silently rewrites the plan | ✓ Good — v4.0 |

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
*Last updated: 2026-06-13 — milestone v5.0 Klaus Hub started (design spec approved; defining requirements).*
