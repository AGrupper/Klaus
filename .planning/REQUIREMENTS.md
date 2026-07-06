# Requirements: Klaus v5.0 — Klaus Hub

**Defined:** 2026-06-13
**Core Value:** Klaus should act as a genuinely intelligent, proactive companion that surfaces the right thing at the right time — while knowing exactly what he is and what he can do.
**Design spec:** `docs/superpowers/specs/2026-06-13-klaus-hub-design.md`

## v1 Requirements

Requirements for milestone v5.0. Each maps to roadmap phases.

### Hub Shell (HUB)

- [x] **HUB-01**: Amit can sign in with Google (allowlisted to his account only) and stay signed in via a session cookie; every `/api/*` route rejects unauthenticated requests
- [x] **HUB-02**: The hub installs as a PWA on the iPhone home screen (manifest, icons, service worker) with explicit in-app Add-to-Home-Screen onboarding
- [x] **HUB-03**: The app shell loads on a bad connection (service-worker pre-cache); API data degrades to skeletons with a visible offline indicator; new deploys are never blocked by a stale cached `index.html`
- [x] **HUB-04**: The frontend is served from the existing `klaus-agent` Cloud Run service without breaking any existing route (Telegram webhook, `/cron/*` OIDC, `/internal/*`, `/trigger/*`)
- [x] **HUB-05**: Desktop shows sidebar + Today timeline + glance rail + collapsible docked Klaus chat; phone shows bottom tabs with Klaus as the center tab — one responsive app

### Klaus Chat (CHAT)

- [x] **CHAT-01**: Amit can chat with Klaus in the hub using the same Firestore conversation history as Telegram — messages from either surface appear in both
- [x] **CHAT-02**: Hub messages are processed via the Cloud Tasks full-CPU path (dedicated `/internal/process-hub-message`), never via Starlette BackgroundTasks
- [x] **CHAT-03**: Sent messages render optimistically with a sending/sent/error status; Klaus's replies arrive via 2–3s polling with a "Klaus is thinking…" indicator while a turn is in flight
- [x] **CHAT-04**: The Klaus tab shows an unread badge counting messages received since last-seen

### Today Timeline (TIME)

- [x] **TIME-01**: The Today timeline shows today's calendar events chronologically (all-day events pinned at top)
- [x] **TIME-02**: The timeline header shows Garmin morning stats (sleep, HRV/body battery) and a one-line weather summary
- [x] **TIME-03**: The timeline shows today's logged meals as slot labels with macros (display-only; never presents slot timestamps as actual eating times)
- [x] **TIME-04**: The timeline shows today's training plan item with block context ("Week N of 16 — Lower Body A")
- [x] **TIME-05**: Events with a location show leave-by / Get Ready times (traffic-aware via routes tool)
- [x] **TIME-06**: Habits and supplements due today appear on the timeline with one-tap check-off
- [x] **TIME-07**: The timeline shows Klaus's one-line coach note for the day (sourced from the morning briefing)
- [x] **TIME-08**: The glance rail shows the day's nutrition running totals (kcal + macros) from MealStore

### Tasks (TASK)

- [x] **TASK-01**: Amit can create, edit, complete, and delete tasks with title, notes, due date, priority, and assign them to **user-creatable lists/projects plus a default Inbox** — stored natively in Firestore `TaskStore` *(revised 2026-06-17, Phase 27 discussion: was "a fixed set of lists")*
- [x] **TASK-02**: Tasks support simple recurrence: daily, weekdays, weekly, monthly, and every-N-days-from-completion (no complex RRULE)
- [x] **TASK-03**: Quick-add (FAB on phone, keyboard shortcut on desktop) parses natural-language dates ("tomorrow", "friday", "next week") while typing
- [x] **TASK-04**: Completing a task gives a satisfying micro-animation; a brief **undo toast** allows recovery from an accidental complete or delete — **completed tasks are not retained (no completed view)** *(revised 2026-06-17, Phase 27 discussion: was "completed tasks remain viewable")*
- [x] **TASK-05**: Klaus manages tasks natively — TickTick tools removed from `core/tools.py`, replaced by TaskStore tools; autonomous Layer-0 gather reads native overdue tasks
- [x] **TASK-06**: Migration off TickTick is **manual** — Amit re-creates his (few) open tasks in the hub; the atomic safety order is preserved: native tasks live + verified (UAT) → TickTick tools removed from `core/tools.py` → subscription cancelled *(revised 2026-06-17, Phase 27 discussion: was "a one-time TickTick import + reconciliation report" — descoped because Amit has few tasks)*
- [x] **TASK-07**: Due and overdue tasks appear on the glance rail and Today timeline

### Habits & Supplements (HABIT)

- [x] **HABIT-01**: Amit can define habits and supplements with name, type (habit|supplement), optional dose, scheduled days, and time-of-day slot in Firestore `HabitStore`
- [x] **HABIT-02**: Each item is checked off with a single tap (from the timeline or Habits tab), with dose shown as a label at check-off
- [x] **HABIT-03**: Streaks count and break only on scheduled days (non-scheduled days are neutral), computed in Asia/Jerusalem local time with DST-boundary tests
- [x] **HABIT-04**: The Habits tab shows a per-habit history grid (contribution-style) in the detail view
- [x] **HABIT-05**: Klaus can read habit/supplement adherence via tools, and the autonomous tick's Layer-0 gather includes today's pending check-offs so he can nudge before end of day

### Web Push & Transition (PUSH)

- [x] **PUSH-01**: Amit can enable push notifications from a button (user gesture) in the installed PWA; subscriptions are stored in `PushSubscriptionStore` and re-validated on hub open
- [x] **PUSH-02**: Klaus's replies and proactive messages arrive as push notifications when the app is closed (`event.waitUntil` wrapped, verified on a physical iPhone)
- [x] **PUSH-03**: Proactive messages mirror to Telegram behind a flag; the mirror runs at least one week before being disabled (Telegram retirement)
- [x] **PUSH-04**: The installed app icon shows an unread-count badge via the Badging API

### Health Pages (HLTH)

- [ ] **HLTH-01**: A training history page visualizes Hevy strength sessions, Garmin run details, and benchmark results from existing stores
- [ ] **HLTH-02**: A nutrition detail page shows macro trends and fueling-slot adherence over time
- [ ] **HLTH-03**: A sleep & recovery page shows HRV, sleep score, and body battery trends

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Hub Extensions

- **HUBX-01**: SSE/streaming chat delivery (only if polling latency becomes a measured pain point)
- **HUBX-02**: Firestore-backed sessions (survive Cloud Run cold starts; in-process acceptable for v5.0)
- **HUBX-03**: Music / Spotify / YouTube widgets and PC-control launcher (Amit's "someday" vision)
- **HUBX-04**: Calendar event editing in the hub beyond what Klaus does via chat
- **HUBX-05**: Offline write queue (tasks/habits created offline sync on reconnect)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time token streaming / WebSockets | Cloud Tasks architecture delivers complete replies; Cloud Run scale-to-zero fights keepalives; polling is honest and sufficient |
| Complex recurrence (RRULE engine) | DST/month-end bug factory; 4 simple patterns + every-N-days cover personal use; edge cases go through Klaus chat |
| Nutrition data entry in the hub | Lifesum → HealthKit pipeline is established and working; a second entry path creates sync conflicts (explicit user decision) |
| Subtasks / task hierarchies | Single-user personal use; plan complex projects conversationally with Klaus |
| Collaboration features | Single user throughout |
| Pomodoro / time tracking | No connection to workflow; zero coaching data value |
| Habit grid on home screen | Noise vs glanceability; grid lives in the Habits tab detail (HABIT-04) |
| Full month mini-calendar in rail | Competes with actionable items; Calendar tab is one tap away |
| Favicon badge libraries | Installed PWA uses the Badging API (PUSH-04), not browser favicons |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HUB-01 | Phase 26 | Complete |
| HUB-02 | Phase 26 | Complete |
| HUB-03 | Phase 26 | Complete |
| HUB-04 | Phase 26 | Complete |
| HUB-05 | Phase 26 | Complete |
| CHAT-01 | Phase 26 | Complete |
| CHAT-02 | Phase 26 | Complete |
| CHAT-03 | Phase 26 | Complete |
| CHAT-04 | Phase 26 | Complete |
| TIME-01 | Phase 26 | Complete |
| TIME-02 | Phase 26 | Complete |
| TIME-03 | Phase 26 | Complete |
| TIME-04 | Phase 26 | Complete |
| TIME-05 | Phase 26 | Complete |
| TIME-07 | Phase 26 | Complete |
| TIME-08 | Phase 26 | Complete |
| TASK-01 | Phase 27 | Complete |
| TASK-02 | Phase 27 | Complete |
| TASK-03 | Phase 27 | Complete |
| TASK-04 | Phase 27 | Complete |
| TASK-05 | Phase 27 | Complete |
| TASK-06 | Phase 27 | Complete |
| TASK-07 | Phase 27 | Complete |
| HABIT-01 | Phase 28 | Complete |
| HABIT-02 | Phase 28 | Complete |
| HABIT-03 | Phase 28 | Complete |
| HABIT-04 | Phase 28 | Complete |
| HABIT-05 | Phase 28 | Complete |
| TIME-06 | Phase 28 | Complete |
| PUSH-01 | Phase 29 | Complete |
| PUSH-02 | Phase 29 | Complete |
| PUSH-03 | Phase 29 | Complete |
| PUSH-04 | Phase 29 | Complete |
| HLTH-01 | Phase 30 | Pending |
| HLTH-02 | Phase 30 | Pending |
| HLTH-03 | Phase 30 | Pending |

**Coverage:**
- v1 requirements: 36 total
- Mapped to phases: 36
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-13*
*Last updated: 2026-06-17 — TASK-01/04/06 revised during Phase 27 discussion (user-creatable lists; completed tasks not retained + undo toast; manual TickTick migration instead of an import script). See `.planning/phases/27-tasks/27-CONTEXT.md` D-02/D-13/D-08.*
