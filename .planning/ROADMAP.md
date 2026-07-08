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
- [ ] **v5.0 — Klaus Hub** — Phases 26–30 (in progress)

---

## v5.0 — Klaus Hub (Phases 26–30) — In Progress

A React + TypeScript PWA served from the `klaus-agent` Cloud Run service that becomes
Klaus's primary interface — replacing Telegram for chat, TickTick for tasks, and the
separate habit tracker. Today timeline as the home screen (phone and desktop), full
Klaus chat sharing the Telegram Firestore conversation, native task and habit/supplement
management, Web Push notifications with Telegram mirror transition, and health pages
visualizing training, nutrition, and sleep data from existing stores.

**Phases:** 5 (26–30) · **Requirements:** 36/36 · Design spec: `docs/superpowers/specs/2026-06-13-klaus-hub-design.md`

## Phases

- [x] **Phase 26: Hub Shell** — React PWA scaffold, Google auth, FastAPI serving, Today timeline, Klaus chat MVP (completed 2026-06-15)
- [x] **Phase 27: Tasks** — Native TaskStore, hub task pages, Klaus tool swap (TickTick → native), manual TickTick migration (completed 2026-06-24)
- [x] **Phase 28: Habits & Supplements** — HabitStore, check-off UI, streaks, Klaus integration, habits on timeline (completed 2026-06-30)
- [x] **Phase 29: Web Push & Transition** — VAPID push, Telegram mirror flag, unread badge, Telegram retirement path (completed 2026-07-04)
- [ ] **Phase 30: Health Pages** — Training history, nutrition detail, sleep & recovery trend visualizations

## Phase Details

### Phase 26: Hub Shell
**Goal**: Amit can open the Klaus Hub on phone or desktop, sign in with Google, see today's full timeline (calendar, meals, training plan, Garmin stats, weather, leave-by times, coach note), and exchange chat messages with Klaus — all reflected in the Telegram conversation history
**Depends on**: Nothing (first phase of v5.0)
**Requirements**: HUB-01, HUB-02, HUB-03, HUB-04, HUB-05, CHAT-01, CHAT-02, CHAT-03, CHAT-04, TIME-01, TIME-02, TIME-03, TIME-04, TIME-05, TIME-07, TIME-08
**Success Criteria** (what must be TRUE):
  1. Amit can open the hub in Safari on iPhone, tap "Add to Home Screen", install it as a PWA, and sign in with his Google account; unauthenticated requests to `/api/*` are rejected
  2. The Today timeline shows calendar events in chronological order with all-day events pinned, Garmin morning stats (sleep/HRV/body battery) and a one-line weather summary in the header, today's meals as slot labels with macros (no eating-time inference), and the training plan item with block context ("Week N of 16 — Lower Body A")
  3. Events with a location show a traffic-aware leave-by / Get Ready time; the glance rail shows the day's running nutrition totals; the timeline shows Klaus's morning coach note
  4. Amit can send a message to Klaus from the hub chat, see it rendered optimistically with a sending/sent status, and receive Klaus's reply via polling with a "Klaus is thinking…" indicator; the same exchange is visible in Telegram
  5. Desktop shows sidebar + timeline + glance rail + collapsible docked chat; phone shows bottom tabs with Klaus as the center tab — one responsive layout
  6. The app shell loads and renders skeletons on a bad connection; a stale cached `index.html` never blocks a new deploy; the frontend is served from `klaus-agent` without breaking any existing route (Telegram webhook, `/cron/*`, `/internal/*`, `/trigger/*`)
**Plans**: 9 plans (5 waves)
- [x] 26-01-PLAN.md — Frontend toolchain (Vite/React/TS/Tailwind/PWA) + multi-stage Dockerfile + SPAStaticFiles mount (HUB-03, HUB-04)
- [x] 26-02-PLAN.md — Backend data foundation: session_version + telegram_user_id + daily_note + itsdangerous + Wave 0 test stubs (HUB-01 scaffold, TIME-07, CHAT-01)
- [x] 26-03-PLAN.md — Hub auth: GIS verify + signed session cookie + require_hub_session + /api/auth/* + SignInPage (HUB-01)
- [x] 26-04-PLAN.md — /api/today composition: calendar/Garmin/weather/meals/training/leave-by/coach-note/nutrition totals (TIME-01..05, TIME-08)
- [x] 26-05-PLAN.md — Chat backend: /api/chat + /api/chat/messages + /internal/process-hub-message + enqueue_hub_message (CHAT-01..04)
- [x] 26-06-PLAN.md — Responsive app shell + routing + auth gate + apiFetch (HUB-05, HUB-01)
- [x] 26-07-PLAN.md — Today timeline UI: now-line/auto-scroll/past-dimming/placeholders + glance rail (TIME-01..05, TIME-08)
- [x] 26-08-PLAN.md — Chat UI: optimistic send + polling + thinking indicator + unread badge (CHAT-03, CHAT-04)
- [x] 26-09-PLAN.md — PWA polish: iOS install banner + offline indicator + skeletons (HUB-02, HUB-03)
**UI hint**: yes

### Phase 27: Tasks
**Goal**: Amit can manage all personal tasks natively in the hub (create, edit, complete, delete, recurrence), Klaus uses native task tools instead of TickTick, and Amit manually re-creates his open TickTick tasks before the subscription is cancelled
**Depends on**: Phase 26
**Requirements**: TASK-01, TASK-02, TASK-03, TASK-04, TASK-05, TASK-06, TASK-07
**Success Criteria** (what must be TRUE):
  1. Amit can create a task with title, notes, due date, priority, and a user-created list/project (or Inbox); edit, complete, and delete it — all persisted in Firestore `TaskStore`
  2. A task can recur on a simple schedule (daily, weekdays, weekly, monthly, or every-N-days), with a per-task anchor toggle (stick-to-schedule vs from-completion); completing one instance generates the next correctly
  3. Quick-add (FAB on phone, keyboard shortcut on desktop) accepts natural-language dates ("tomorrow", "next week", "friday") plus `#list` / `!priority` tokens and resolves them while typing
  4. Completing a task produces a visible micro-animation; a brief undo toast allows recovery — completed tasks are not retained (no completed view)
  5. Klaus manages tasks via native tools in `core/tools.py` (TickTick tools removed); the autonomous Layer-0 gather reads native overdue tasks; due and overdue tasks appear on the glance rail and Today timeline
  6. Amit manually re-creates his open TickTick tasks in `TaskStore`; the migration order is preserved — native tasks verified (UAT) → TickTick tools removed → subscription cancelled
**Plans**: 7 plans (5 waves)
- [x] 27-01-PLAN.md — TaskStore + TaskListStore + recurrence engine + Wave 0 tests + composite indexes (TASK-01/02/04/07)
- [x] 27-02-PLAN.md — /api/tasks/* + /api/task-lists/* CRUD + summary + Pydantic validation (TASK-01/02/04/07)
- [x] 27-03-PLAN.md — Klaus native task tool swap + autonomous overdue gather repoint (TASK-05)
- [x] 27-04-PLAN.md — Frontend data layer: chrono-node + parseTaskInput + api/hooks + undoStore (TASK-01/03/04/07)
- [x] 27-05-PLAN.md — Tasks page UI: list/row/detail-sheet/recurrence/sort + completion animation + undo (TASK-01/02/04)
- [x] 27-06-PLAN.md — Quick-add (FAB + N-key) + Due-today timeline band + glance-rail tasks section (TASK-03/07)
- [x] 27-07-PLAN.md — TickTick cutover: UAT gate → manual migration → remove TickTick files (TASK-05/06)
**UI hint**: yes

### Phase 28: Habits & Supplements
**Goal**: Amit can define and track daily habits and supplements natively in the hub with streaks and adherence history, Klaus can read adherence state and nudge via the autonomous tick, and habit/supplement items appear on the Today timeline for one-tap check-off
**Depends on**: Phase 26
**Requirements**: HABIT-01, HABIT-02, HABIT-03, HABIT-04, HABIT-05, TIME-06
**Success Criteria** (what must be TRUE):
  1. Amit can define a habit or supplement with name, type, optional dose, scheduled days, and time-of-day slot; items are stored in Firestore `HabitStore`
  2. A single tap on a habit or supplement (from the timeline or Habits tab) marks it complete; supplements show their dose label at check-off
  3. Streaks count correctly for scheduled days only (non-scheduled days are neutral) and reset on a missed scheduled day, computed in Asia/Jerusalem local time passing DST-boundary tests
  4. The Habits tab detail view shows a per-habit contribution-style history grid
  5. Habits and supplements due today appear on the Today timeline with one-tap check-off; Klaus can read today's pending check-offs via tools; the autonomous tick's Layer-0 gather includes habit adherence state so the tick-brain can judge end-of-day nudges
**Plans**: TBD
**UI hint**: yes

### Phase 29: Web Push & Transition
**Goal**: Amit receives Klaus's replies and proactive messages as native push notifications on the installed iPhone PWA when the app is closed, Telegram continues to mirror all messages during a transition period, and the installed icon shows an unread-count badge
**Depends on**: Phase 26
**Requirements**: PUSH-01, PUSH-02, PUSH-03, PUSH-04
**Success Criteria** (what must be TRUE):
  1. Amit can enable push notifications from a button (requiring a user gesture) inside the installed PWA; the VAPID subscription is stored in `PushSubscriptionStore` and re-validated on each hub open
  2. Klaus's replies and proactive autonomous-tick messages are delivered as push notifications to the iPhone when the app is closed, wrapped in `event.waitUntil` and verified on a physical device
  3. Proactive messages mirror to Telegram behind a flag that is left ON for at least one week before being disabled; the mirror path is validated in production before Telegram retirement is considered
  4. The installed PWA icon shows an unread-count badge via the Badging API (not a favicon library)
**Plans**: 10 plans
- [x] 29-01-PLAN.md — Backend deps (pywebpush) + VAPID secret setup + docs
- [x] 29-02-PLAN.md — Frontend workbox devDeps + 29-HUMAN-UAT.md
- [x] 29-03-PLAN.md — PushSubscriptionStore + HubSettingsStore (Firestore)
- [x] 29-04-PLAN.md — core/push_sender.py fan-out (TTL, 404/410 cleanup, VAPID)
- [x] 29-05-PLAN.md — Brain tools (mirror toggle + push health) + heartbeat checker
- [x] 29-06-PLAN.md — /api/push/* + /api/settings routes
- [x] 29-07-PLAN.md — generateSW→injectManifest custom service worker (push + badge)
- [x] 29-08-PLAN.md — send_and_inject push/mirror/visibility + all 3 send paths
- [x] 29-09-PLAN.md — usePush + useAppBadge hooks
- [x] 29-10-PLAN.md — Settings page + enable banner + nav + device UAT

### Phase 30: Health Pages
**Goal**: Amit can view his training history, nutrition trends, and sleep/recovery patterns visually in the hub, drawing from the existing Firestore stores built in v3.0–v4.0 and the post-v4.0 increments
**Depends on**: Phase 26
**Requirements**: HLTH-01, HLTH-02, HLTH-03
**Success Criteria** (what must be TRUE):
  1. A training history page shows Hevy strength sessions, Garmin run details, and benchmark results from `StrengthSessionStore`, `RunDetailStore`, and `BenchmarkStore` — browsable by date range
  2. A nutrition detail page shows macro trends and fueling-slot adherence over time from `MealStore` — distinguishes calories/protein/carbs/fat/fiber with a slot-view
  3. A sleep & recovery page shows HRV trend, sleep score, and body battery readings from Garmin data with visible patterns over days and weeks
**Plans**: 8 plans (5 waves)
- [x] 30-01-PLAN.md — Backend data layer: BenchmarkStore.get_range + core/health_reads.py::fetch_biometric_range (HLTH-01, HLTH-03)
- [x] 30-02-PLAN.md — 3 /api/health/* routes (training/nutrition/sleep) behind require_hub_session + Wave 0 API tests (HLTH-01/02/03)
- [x] 30-03-PLAN.md — Hand-rolled SVG chart toolkit: LineChart/BarChart/ChartTooltip/ChartCard/ChartEmptyState + D-08 gap tests (HLTH-01/02/03)
- [ ] 30-04-PLAN.md — Frontend data layer: api/health.ts + useHealth hooks + SubTabs (persisted) + RangeToggle (HLTH-01/02/03)
- [ ] 30-05-PLAN.md — Training History page: mixed color-coded log + block dividers + trend charts + drill-down sheets (HLTH-01)
- [ ] 30-06-PLAN.md — Nutrition Detail page: macro chip/trend + slot-adherence grid + day drilldown (slot-label invariant) (HLTH-02)
- [ ] 30-07-PLAN.md — Sleep & Recovery page: header stats + HRV/sleep/body-battery charts + pipeline-not-live guard (HLTH-03)
- [ ] 30-08-PLAN.md — Wire HealthPage root + App.tsx swap + full-suite gate + device UAT (HLTH-01/02/03)
**UI hint**: yes

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 26. Hub Shell | 9/9 | Complete    | 2026-06-16 |
| 27. Tasks | 7/7 | Complete    | 2026-06-24 |
| 28. Habits & Supplements | 5/5 | Complete    | 2026-07-02 |
| 29. Web Push & Transition | 10/10 | Complete    | 2026-07-06 |
| 30. Health Pages | 3/8 | In Progress|  |

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
