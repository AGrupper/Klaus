# Klaus Hub — Design Spec

**Date:** 2026-06-13
**Status:** Approved (brainstormed with visual mockups; layout locked)
**Scope:** Milestone-sized — to be scoped as v5.0 via `/gsd-new-milestone`

## 1. What it is

A web app (React + TypeScript PWA) that becomes **Klaus's primary interface** — replacing
Telegram for chat, TickTick for tasks, and the separate habit tracker — plus a live view of
nutrition, training, calendar, and health. Installed on Amit's iPhone home screen and opened
as an app window on the PC. Served from the existing `klaus-agent` Cloud Run service.

### Goals

- One place to see everything going on (day timeline, tasks, habits, nutrition, training)
- One place to talk to Klaus (full chat, eventually replacing Telegram)
- Drop subscriptions: TickTick and the habit-tracker app become native features

### Non-goals (deferred to someday)

- Music / Spotify / YouTube widgets and PC control — explicitly deferred
- Replacing Lifesum: nutrition stays on the Lifesum → HealthKit pipeline, display-only
- Replacing Google Calendar: it remains the backend; hub displays and creates events

## 2. Decisions made during brainstorming

| Question | Decision |
|----------|----------|
| Usage context | Phone + desktop equally (responsive PWA) |
| Replace vs display | Replace TickTick + habit tracker natively; nutrition display-only |
| Klaus presence | Full chat — hub is intended to replace Telegram |
| Notifications | Hybrid transition: Web Push + Telegram mirror behind a flag until trusted |
| Supplements | Habit-style daily check-offs **with a dose field** Klaus can read; no inventory |
| Hosting | Served from `klaus-agent` Cloud Run (same origin, one deploy, no CORS) |
| Phone chat access | Klaus as the **center tab** in the bottom tab bar |

## 3. Layout (locked via mockups)

**Desktop:** slim icon sidebar (Today / Tasks / Habits / Health / Calendar) · center =
Today timeline · glance rail (nutrition, due tasks, streaks) · Klaus chat docked right,
collapsible for full-width organizing.

**Phone:** bottom tab bar — Today · Tasks · **Klaus (center, full-screen chat with unread
badge)** · Habits · Health. Today timeline is the home screen.

## 4. Architecture

- **Frontend:** React + TypeScript + Vite PWA (service worker for Web Push +
  installability), Tailwind. Built assets served by FastAPI from the klaus-agent container.
- **Auth:** Google Sign-In allowlisted to Amit's account → session cookie. All hub API
  routes live under `/api/*` and require the session; existing webhook and `/cron/*`
  routes are untouched.
- **Chat:** reuses the existing Firestore conversation (`memory/firestore_conversation.py`)
  — one shared history with Telegram, one Klaus. Outbound: `POST /api/chat` → enqueue via
  `core/task_dispatch.py` → `/internal/process-update` (same full-CPU Cloud Tasks path as
  Telegram). Replies: client polls while the app is open (v1; SSE later if needed); Web
  Push when closed. `core/scheduled_message.py` gains hub delivery (push) alongside a
  Telegram mirror flag for proactive messages.
- **New Firestore stores** (following `memory/firestore_db.py` patterns):
  - `TaskStore` — title, notes, due, priority, list, simple recurrence, completed_at
  - `HabitStore` — definition (name, type habit|supplement, optional dose, schedule
    days + slot) + daily completion log; streak computation
  - `PushSubscriptionStore` — Web Push (VAPID) subscriptions
- **Klaus tool changes** (`core/tools.py`): swap `mcp_tools/ticktick_tool.py` for native
  task tools; add habit/adherence tools; extend the autonomous Layer-0 gather
  (`core/autonomous.py`) with today's habit/supplement state so the tick-brain can judge
  adherence nudges.
- **Today timeline:** one `/api/today` endpoint composes the day server-side: calendar
  events (+ leave-by / Get Ready via `mcp_tools/routes_tool.py`), meals from MealStore
  (slot-time caveat — never infer eating time), habits/supplements due, training plan
  items, Garmin morning stats, weather.

## 5. Build phases (each independently shippable)

1. **Shell** — frontend scaffold + static serving from FastAPI, Google auth, read-only
   Today timeline, chat MVP (send + poll)
2. **Tasks** — TaskStore + hub task pages + Klaus tool swap + one-time TickTick import
   script → drop TickTick
3. **Habits/supplements** — HabitStore + check-off UI + streaks + Klaus integration →
   drop habit app
4. **Web Push** — VAPID push + Telegram mirror flag → eventually retire Telegram
5. **Health pages** — training history (Hevy/Garmin stores), nutrition detail, sleep trends

## 6. Verification

- Per phase: new stores/routes get pytest coverage following existing patterns in `tests/`.
- Phase-1 UAT: open the hub on iPhone (installed PWA) and desktop, sign in, see today's
  real timeline, exchange a chat message with Klaus and see the same exchange reflected
  in the Telegram-side history.
- Phase-2 UAT: create/complete a task in the hub; ask Klaus to reschedule it; verify
  TickTick import completeness before cancelling the subscription.
- Phase-4 UAT: receive an autonomous-tick outreach as Web Push on iPhone with the
  Telegram mirror on; run for a week before disabling the mirror.
