# Feature Research

**Domain:** Personal AI hub — web PWA replacing Telegram chat + TickTick + habit tracker, with Today timeline and health pages (Klaus v5.0)
**Researched:** 2026-06-13
**Confidence:** HIGH (task/habit/PWA patterns well-established in best-in-class apps; Klaus-specific integration constraints are HIGH from reading design spec + existing codebase)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features Amit will immediately notice are missing. Not having these makes the hub feel incomplete vs the apps it replaces.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Task: title + due date + priority | Every task manager has these three | LOW | Title is the only truly required field; due and priority are optional at capture, editable later. No subtasks needed for single user. |
| Task: simple recurrence | Daily, weekdays, weekly, monthly — the four patterns covering ~95% of personal recurrence needs | MEDIUM | "Every N days from completion" is expected for supplement reminders. Complex RRULE patterns (every 3rd Thursday, last weekday of month) are TickTick power features safe to omit — they require a full rule engine that creates bugs at DST boundaries and month-end. |
| Task: quick-add with low friction | TickTick and Todoist have trained users to expect one-action task capture | LOW | A floating FAB (phone) or keyboard shortcut (⌘K / Q on desktop) opening a focused input. Parse "tomorrow", "Friday", "next week" as due dates. The friction here directly determines whether Amit will stop using the app. |
| Task: list/group assignment | TickTick users organize by area of life | LOW | Two to four hardcoded lists (Personal, Health, Work, Someday) is enough for a single user. Dynamic list creation is a nice-to-have, not table stakes at launch. |
| Task: mark complete with satisfying animation | Checkmark is the primary reward mechanism in task apps | LOW | The completion micro-animation matters psychologically — it's the dopamine hit that makes task apps sticky. |
| Habit: scheduled days per habit | "Gym Mon/Wed/Fri" must not demand a Monday check-off on Tuesday | MEDIUM | Streak must only count or break on scheduled days. Non-scheduled days are neutral — not missed. This is the core model of Streaks (iOS Apple Design Award winner). |
| Habit: single-tap check-off | Under 10 seconds to log; longer = users stop doing it | LOW | One tap per habit per day. No sub-prompts. Simplicity here is not laziness — it's the reason habit apps succeed or fail. |
| Habit: streak display | "7-day streak" or flame icon on each habit card | LOW | Consecutive scheduled-day completions. Streak breaks only when user misses a scheduled day, not on skip/rest days. Streak count is the primary motivation signal. |
| Habit: dose display for supplements | Vitamin D 2000 IU, Creatine 5g — dose is what distinguishes a supplement from a generic habit | LOW | Dose is display-only at check-off time — shown as a reminder label, not re-entered. Stored in HabitStore definition once, referenced at every check-off. |
| Chat: optimistic send (message appears instantly) | Any delay between tapping Send and seeing the message looks like a bug | LOW | User's message renders immediately in the chat UI before Cloud Tasks confirms. Status indicator below it: "sending" → "sent" → "error". |
| Chat: reply polling while app is open | Klaus replies asynchronously; user needs to see the reply when it arrives | MEDIUM | Poll every 2-3 seconds while the chat tab is active. Animated "Klaus is thinking..." indicator while awaiting reply. Stop polling when a reply arrives or when the tab loses focus. |
| Chat: conversation history | The same history Telegram has — shared Firestore conversation | LOW | Reuses `firestore_conversation.py` exactly. No new data model. Telegram messages appear in hub history and vice versa — intentional. |
| Chat: unread badge on Klaus tab | When Klaus sends a proactive autonomous message and Amit is on another tab, there must be a visible signal | LOW | Count of messages since last-seen timestamp. The center-tab placement on phone makes this badge the primary notification signal before push is configured. |
| Today timeline: calendar events | What is happening today, in time order — the most critical home-screen data | LOW | Reads from existing `calendar_tool.py`. Timed events shown chronologically; all-day events pinned at top. |
| Today timeline: habits and supplements due today | Which ones are pending right now vs already checked off | LOW | Filter HabitStore by today's scheduled days. Completed = checked/colored, pending = unchecked. One-tap check-off from the timeline directly. |
| Today timeline: Garmin morning stats | Sleep score, HRV, body battery — already gathered every morning | LOW | Display-only; reads from existing morning briefing data / `garmin_tool.py`. Three numbers, not a paragraph. |
| Today timeline: weather | Temperature and rain forecast — already in `weather_tool.py` | LOW | One line on the glance rail or at the top of the timeline. Do not show a full 7-day forecast on the home screen — information overload. |
| Today timeline: meals (display only) | What has been logged via HealthKit today | LOW | Read from `MealStore.get_day()`. Show "Breakfast logged: 42g protein, 85g carbs" — slot labels only, never infer eating time from the slot timestamps (Lifesum caveat: slot times are canonical, not actual eating times). |
| PWA: installable on iOS home screen | Users who "install" it expect an app-like standalone experience | MEDIUM | Requires: HTTPS, web app manifest with 192px + 512px icons, service worker registration. iOS shows no automatic install prompt — must provide clear "Add to Home Screen" instructions in the UI. Without installation, Web Push does not work on iOS. |
| PWA: offline shell | A blank white screen on a bad connection destroys trust in the app | MEDIUM | Service worker pre-caches app shell (HTML/CSS/JS bundles). API data can fail gracefully with skeleton loaders. iOS enforces 7-day cache expiry — users who open weekly always get a fresh cache hit. 50MB storage ceiling applies; app shell easily fits. |
| Google auth gate | Single user; no anonymous access to Amit's personal data | LOW | Google Sign-In → session cookie. Every `/api/*` route requires the session. Existing `/webhook` and `/cron/*` routes are completely untouched. |

### Differentiators (Competitive Advantage)

Features that make the hub genuinely better than Telegram + TickTick + habit app combined — because Klaus knows everything about Amit.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Today timeline: training plan item | What is on the training plan today (Upper/Lower/Rest, current block week) — no other app knows this | MEDIUM | Reads from UserProfileStore weekly_split + BlockStore current week. "Week 7 of 16 — Lower Body A" displayed on the timeline. No other personal dashboard has this. |
| Today timeline: leave-by and Get Ready time | "Leave by 08:15 for your 09:00 gym appointment — 15 min travel + 45 min Get Ready" — from live traffic via `routes_tool.py` | MEDIUM | Already works in `calendar_tool.py`. Surface it on the Today timeline for any event with a location. Real utility; no other personal dashboard does this. |
| Autonomous-tick habit adherence awareness | Klaus knows at tick time (every 20 min, 07:00–21:00) which habits and supplements are still pending; can nudge before end of day | MEDIUM | Extend Layer-0 gather in `autonomous.py` to read today's HabitStore completion state. Tick-brain then decides: "Sir, Creatine not yet logged — it is 20:30." Cheapest path to proactive supplement accountability. |
| Chat shares Telegram history seamlessly | One brain, one memory — switching mid-day from Telegram to hub or back works with zero setup | LOW | Zero extra implementation — same Firestore conversation store. Telegram messages appear in hub; hub messages appear in Telegram during the transition period. Genuine differentiator vs any third-party chat UI. |
| Supplement dose as a first-class habit field | No separate supplement app needed; dose is visible at check-off; Klaus reads adherence in coaching context | LOW | HabitStore `type=supplement` + `dose` string field. Klaus's coaching prompts can cite: "Creatine 5g: checked off 5/7 days this week." |
| Tasks via Klaus natural language | "Add a task to call the dentist Friday p1" — Klaus creates it in native TaskStore instead of TickTick via the tool swap | LOW | Tool swap in `core/tools.py`. The real differentiator is that Klaus can proactively surface overdue tasks, reschedule conflicts, and reference task state in coaching context. |
| Glance rail: due tasks + current streaks | Desktop right rail shows what needs attention today — tasks due or overdue + habit streak counts — at a glance without opening any tab | LOW | Pure filtered reads: TaskStore (due today / overdue) + HabitStore (streak count per habit). No computation required; very low implementation cost for high daily utility. |
| Health pages: training history with coaching context | Hevy sessions, Garmin runs, benchmark results — visualized with Klaus's coaching annotations inline | HIGH | Requires composing Hevy StrengthSessionStore + BenchmarkStore + RunDetailStore + coaching context. All underlying data already exists. This is visualization work, not data-pipeline work. Phase 5 appropriately. |
| Web Push as Telegram replacement | Receive autonomous-tick outreaches as native iOS push notifications, eliminating Telegram dependency over time | MEDIUM | VAPID push + PushSubscriptionStore. Telegram mirror flag allows hybrid transition: both channels active simultaneously until trust is established, then mirror turned off. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Real-time token streaming in chat | Feels faster; ChatGPT-style | Klaus's Cloud Tasks architecture delivers one complete reply after the full agent turn. There is no token stream available at the client boundary. Faking streaming via SSE would require restructuring the entire agent loop and is not warranted for a single-user app. | Polling every 2-3 seconds with an animated "Klaus is thinking..." indicator is honest and appropriate for this architecture. Add SSE as an enhancement only if turn latency becomes a measured pain point. |
| WebSocket persistent connection for chat | Lower latency, more "real-time" | Cloud Run scales to zero between requests. WebSocket keepalive pings fight the scale-to-zero behavior and drive unnecessary cost. Single-user traffic volume does not justify the operational complexity. | HTTP polling while the tab is active + Web Push when backgrounded. Identical UX outcome, simpler operations. |
| Complex recurrence rules (every 3rd Thursday, last weekday of month, bi-weekly on alternating Tuesdays) | Power users want this in task managers | Requires a full RRULE engine (RFC 5545). Bugs surface at DST transitions and month-end edge cases. For single-user personal use, daily / weekdays / weekly / monthly covers nearly all real needs. | Four simple recurrence patterns plus "every N days from completion." For edge cases, tell Klaus in chat and he will manually reschedule. |
| Full calendar create/edit/delete in the hub | "One place for everything" | Google Calendar is the authoritative source-of-truth backend. Bidirectional sync creates conflict-resolution complexity, especially for recurring events and shared calendars. The spec explicitly defers this. | Today timeline shows events read from GCal (display-only). Klaus can create events via `calendar_tool.py` through chat — that path already works and is the correct model. |
| Nutrition data entry or meal logging in the hub | Seems natural for a health hub | Lifesum → HealthKit is the established pipeline that already works. Duplicating entry in the hub would create sync conflicts and a second competing data source. Amit explicitly decided nutrition is display-only in the hub. | Display MealStore data beautifully; coach on adherence via Klaus chat. The logging pipeline is solved — do not rebuild it. |
| GitHub-style habit contribution grid on the home screen | Visually impressive; motivating | The grid shows months of history, requiring horizontal scrolling or a large card. It is noise on the home screen where glanceability is the goal. Showing 180 colored squares competes with today's actual actionable items. | Show streak count + today's check-off status on the Today timeline and Habits tab header. Full calendar grid available in the Habits tab detail view only — where the user is already in the context of reviewing history. |
| Subtasks and task hierarchies | Power feature in Todoist and TickTick | Single-user personal use rarely requires true parent-child task relationships. The UI required to capture, display, and navigate subtasks adds friction to the common case (a simple task) for a rare case (a hierarchical project). | Use Klaus chat to plan complex projects conversationally. Track atomic, actionable tasks in TaskStore. |
| Collaborative features (sharing, assignees, team views) | Standard in team task apps | Single user throughout v5.0 and the foreseeable future. Adds zero value and nonzero complexity. | Explicitly out of scope per design spec and PROJECT.md. |
| Always-visible full calendar in sidebar or glance rail | Comprehensive time awareness | The Today timeline already shows today's events in order. A mini-calendar showing a full month adds 30+ cells of information competing with actionable items. The Calendar tab exists for this view. | Show "next event" summary or a 3-day strip in the glance rail at most. Full calendar is one tab navigation away. |
| Pomodoro timer or time-tracking | TickTick includes this; feels productive | No connection to Amit's workflow. Adds a stateful timer UI requiring active management. Zero data value to Klaus's coaching or autonomous reasoning. | Not included at any phase. |
| Favicon badge count for unread messages | Looks polished in the browser tab | The iOS PWA installed to home screen uses the Web App Badging API on the icon — not the browser favicon. Favicon badging only matters when the browser tab is open, which is not the primary usage mode for an installed PWA. | Use `navigator.setAppBadge(count)` for the home screen icon badge (Badging API, iOS 16.4+). Also update the in-app tab badge. Do not invest in favicon badge libraries. |
| Offline task creation and sync | Seems like a good PWA feature | Requires an offline queue with conflict resolution for server-sync on reconnect. For a single-user personal hub used on a phone that is almost always online, the complexity is not worth the edge case. | Cache the app shell and recent data for offline reading. Show a clear "you are offline" indicator for write operations. |

---

## Feature Dependencies

```
[Google Auth]
    └──required by──> ALL /api/* routes (every hub feature)

[Service Worker registration (Phase 1)]
    └──required by──> [Web Push subscriptions (Phase 4)]
    └──required by──> [Offline shell (Phase 1)]
    └──required by──> [PWA installability — manifest works without SW, but push does not]
    └──required by──> [Badging API (requires installed PWA + notification permission)]

[HabitStore (Phase 3)]
    └──required by──> [Habit check-off UI]
    └──required by──> [Streak computation]
    └──required by──> [Dose display at check-off]
    └──required by──> [Habits on Today timeline]
    └──required by──> [Autonomous-tick habit awareness (Layer-0 gather extension)]
    └──required by──> [Klaus coaching supplement-adherence references]

[TaskStore (Phase 2)]
    └──required by──> [Hub task pages]
    └──required by──> [Klaus tool swap — TickTick tool removed, native tools added]
    └──required by──> [Glance rail due-tasks view]
    └──required by──> [Tasks on Today timeline]

[TickTick import script (Phase 2)]
    └──must precede──> [TickTick subscription cancellation]
    └──must precede──> [Klaus tool swap being deployed]
    (TaskStore must be populated before the tool swap or Klaus loses task history)

[PushSubscriptionStore (Phase 4)]
    └──required by──> [Web Push delivery]
    └──required by──> [Telegram mirror flag logic in scheduled_message.py]

[Web Push trusted for 1+ week (Phase 4 UAT)]
    └──enables──> [Telegram mirror flag turned OFF → Telegram retirement]

[Health pages (Phase 5)]
    └──requires──> [StrengthSessionStore — already built (Hevy)]
    └──requires──> [RunDetailStore — already built (Garmin)]
    └──requires──> [MealStore — already built (HealthKit)]
    └──requires──> [Garmin sleep/HRV data — already built]
    (All underlying data already exists; health pages are visualization only)

[Klaus tool swap (Phase 2)]
    └──conflicts with──> [TickTick tool still active in tools.py]
    (Cannot run both simultaneously — swap must be atomic: import → swap → UAT → cancel subscription)
```

### Dependency Notes

- **Auth is the root dependency.** Google Sign-In ships in Phase 1. Nothing else is accessible without it.
- **Service worker is the PWA unlock.** Registering it in Phase 1 enables push, offline, and home-screen badging — even if push subscriptions are not yet collected until Phase 4.
- **HabitStore precedes autonomous awareness.** The tick-brain habit-nudge feature requires HabitStore to have data. This extension ships in Phase 3, not Phase 1 or 2.
- **Tool swap must be atomic.** Running both TickTick tool and TaskStore tool simultaneously creates ambiguity in Klaus's tool dispatch. The TickTick import runs first (populates TaskStore), then the tool swap is deployed, then the subscription is cancelled after UAT confirms data integrity.
- **Health pages have no new data dependencies.** All underlying stores are built and deployed. Phase 5 is pure visualization — it is additive to the shell with no backend changes required beyond new read endpoints.
- **Web Push mirror must run for at least one week before Telegram mirror is turned off.** This is an explicit UAT requirement in the design spec. Phase 4 ships with mirror ON; mirror is turned OFF manually after validated trust.

---

## MVP Definition

This is a subsequent milestone (v5.0) on an existing working system. Each phase is independently shippable per the design spec.

### Phase 1 — Shell (Launch With)

- [ ] Google auth gate — without this, nothing else is accessible
- [ ] Today timeline (read-only): calendar events, Garmin stats, weather, meals, training plan item — validates the "glanceable day" value proposition
- [ ] Chat: send + poll for reply + conversation history — validates the Telegram replacement story
- [ ] Unread badge on Klaus tab — without this, chat feels broken when Klaus sends a proactive message
- [ ] PWA manifest + service worker (offline shell + installable on iOS home screen)
- [ ] Leave-by / Get Ready time on Today timeline — low complexity; high daily value

### Phases 2-3 — Core Replacements (Add After Shell Validates)

- [ ] TaskStore + full task CRUD + quick-add — validates TickTick replacement; run for one week before cancelling subscription
- [ ] TickTick one-time import script — must precede subscription cancellation and tool swap
- [ ] Klaus tool swap (TickTick → native TaskStore) — atomic with import deployment
- [ ] HabitStore + check-off UI + streak computation — validates habit-app replacement
- [ ] Dose display for supplements — included in HabitStore schema from day one
- [ ] Autonomous-tick Layer-0 habit gather extension — enables proactive supplement nudges

### Phase 4 — Notifications (When Hub Is Trusted Daily)

- [ ] VAPID Web Push infrastructure + PushSubscriptionStore
- [ ] Telegram mirror flag in `scheduled_message.py`
- [ ] iOS install instructions in the hub (required for push to work on iOS)
- [ ] Badging API integration (`navigator.setAppBadge`)
- [ ] Run with mirror ON for one week → turn mirror OFF after validation

### Phase 5 — Health Pages (Additive; No New Data Pipelines)

- [ ] Training history page: Hevy sessions + Garmin runs + benchmark results
- [ ] Nutrition detail page: macro trends, fueling slot adherence
- [ ] Sleep trends page: HRV, sleep score, body battery over time

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Google auth | HIGH | LOW | P1 |
| Today timeline (calendar + weather + Garmin + meals) | HIGH | LOW | P1 |
| Training plan item on Today | HIGH | LOW | P1 |
| Chat send/poll + history | HIGH | MEDIUM | P1 |
| Unread badge | HIGH | LOW | P1 |
| PWA installable + offline shell | HIGH | MEDIUM | P1 |
| Leave-by / Get Ready time on Today | MEDIUM | LOW | P1 |
| Task CRUD + quick-add | HIGH | MEDIUM | P1 (Phase 2) |
| TickTick import | HIGH | LOW | P1 (Phase 2, enables cancellation) |
| Klaus task tool swap | HIGH | LOW | P1 (Phase 2) |
| Habit check-off + streaks | HIGH | MEDIUM | P1 (Phase 3) |
| Supplement dose display | HIGH | LOW | P1 (Phase 3) |
| Autonomous habit-nudge awareness | HIGH | LOW | P1 (Phase 3, extend existing gather) |
| Glance rail (due tasks + streaks) | MEDIUM | LOW | P2 (Phase 1 or 2) |
| Web Push + Telegram mirror | HIGH | MEDIUM | P2 (Phase 4) |
| Badging API | MEDIUM | LOW | P2 (Phase 4) |
| Health pages (training history) | MEDIUM | MEDIUM | P2 (Phase 5) |
| Health pages (nutrition + sleep) | MEDIUM | MEDIUM | P2 (Phase 5) |
| SSE streaming for chat | LOW | HIGH | P3 (defer; polling works for this architecture) |
| Full calendar create/edit in hub | LOW | HIGH | P3 (defer; GCal is the backend) |
| Offline write queue (sync on reconnect) | LOW | HIGH | P3 (single user, almost always online) |

---

## Competitor Feature Analysis

| Feature | TickTick | Streaks / HabitKit | Our Approach |
|---------|----------|--------------------|--------------|
| Task capture | Natural language (good), floating button + keyboard shortcut | N/A | FAB on phone + ⌘K on desktop. Parse "tomorrow", "Friday", "next week" as due dates. Omit NLP for labels and priority — not worth the parsing complexity for single user. |
| Task recurrence | Full RRULE engine — complex patterns | N/A | Daily / Weekdays / Weekly / Monthly / Every-N-days-from-completion. Five patterns total. |
| Task lists | Multiple lists + smart lists + filters | N/A | Two to four hardcoded lists (Personal, Health, Work, Someday). No dynamic list creation in Phase 2. |
| Habit scheduling | Habits exist in TickTick but are separate from tasks | Specific weekdays, N-times-per-week, N-times-per-month | Specific weekdays per habit. N-times-per-week is a nice-to-have deferred to after launch. |
| Streak rules | N/A | Streak breaks only on scheduled days; other days are neutral; "skip" does not break streak | Same model: streak increments on scheduled-day completions, breaks only when a scheduled day is missed without a check-off. |
| Dose tracking | No | HabitKit supports multi-tap (e.g., "drink 8 glasses"), not dose display | Dose as a definition field (e.g., "Creatine — 5g"), displayed as a label at check-off. Not re-entered daily. Not multi-tap — dose is fixed per habit definition. |
| Today home screen | TickTick "Today" view shows tasks only | HabitKit shows today's habits only | Compose calendar + training plan + habits/supplements + Garmin stats + weather + meals — significantly richer than either. No other personal dashboard has the coaching layer (leave-by times, training block context). |
| AI integration | None | None | Klaus knows everything in the hub and can create tasks, read habit adherence, coach on supplement timing, project training goals. This is the core differentiator that justifies building a custom hub instead of customizing an existing app. |
| Notifications | Push from their cloud service | Push from their cloud service | VAPID push from Klaus's own Cloud Run service (Phase 4). Telegram mirror during transition. |

---

## Klaus-Specific Integration Constraints

These constraints come from the existing codebase and are not discoverable from competitor research. They directly affect feature design.

**Meal slot times are not eating times.** MealStore timestamps are canonical slot times (08:00 / 12:00 / 20:00), not actual eating times. The Today timeline must label meals as "Breakfast logged: 42g protein" — never as "ate at 08:00." This is documented in CLAUDE.md and the USER.md Lifesum caveat.

**Chat turns run via Cloud Tasks, not inline.** The full-CPU path (`/internal/process-update`) is required for correct LLM replies. The hub's `POST /api/chat` must enqueue via `task_dispatch.py` — not execute inline in a request handler. This is the slow-reply fix from 2026-06-12 (commit 80809f9). No token streaming to the client is possible with this architecture. Polling every 2-3 seconds is the correct and honest model.

**Same Firestore conversation as Telegram.** `firestore_conversation.py` stores one history per user ID. The hub reads and writes the same collection. Telegram messages are visible in hub history and vice versa during the transition. This is a feature (continuity), not a bug.

**Autonomous tick already exists and can be extended cheaply.** `autonomous.py` Layer-0 gather runs every 20 minutes, 07:00–21:00, fanning out data collection across a thread pool. Adding a HabitStore read to the gather is a small addition — one more key in the gathered context dict. The tick-brain already has a judgment framework for when to speak up; it just needs the new data to reason about.

**TickTick tool swap must be atomic.** `core/tools.py` registers TickTick handlers via `mcp_tools/ticktick_tool.py`. The Phase 2 swap removes those handlers and registers native TaskStore handlers instead. Both cannot be active simultaneously. Sequence: (1) run import script to populate TaskStore, (2) deploy tool swap, (3) run Phase 2 UAT, (4) cancel TickTick subscription.

**Web Push on iOS requires home-screen installation.** iOS 16.4+ supports Web Push only for PWAs installed from Safari to the home screen. The EU DMA restriction (iOS 17.4+, PWA opens as Safari tab without push) does not apply to Amit in Tel Aviv. Must provide explicit Add-to-Home-Screen instructions in the hub UI — iOS never shows an automatic install prompt.

**Badging API (iOS 16.4+).** Use `navigator.setAppBadge(count)` for the home-screen icon unread count. App icon shortcuts, widgets, and dynamic shortcuts on the iOS long-press menu are not supported for PWAs. Do not invest in these.

---

## Sources

- TickTick vs Todoist comparison: [upbase.io](https://upbase.io/blog/ticktick-vs-todoist/), [morgen.so](https://www.morgen.so/blog-posts/ticktick-vs-todoist), [toolfinder.com](https://toolfinder.com/comparisons/todoist-vs-ticktick)
- Todoist Quick Add documentation: [todoist.com](https://www.todoist.com/help/articles/use-task-quick-add-in-todoist-va4Lhpzz)
- Linear UX speed patterns: [nimpatil.substack.com](https://nimpatil.substack.com/p/the-ux-psychology-behind-linears)
- Streaks app streak rules: [crunchybagel.com](https://crunchybagel.com/now-available-streaks-10/), [habitboard.app](https://habitboard.app/streaks/)
- HabitKit: [habitkit.app](https://www.habitkit.app/), [zapier.com](https://zapier.com/blog/best-habit-tracker-app/)
- Habit tracker iOS best practices: [timingapp.com](https://timingapp.com/blog/habit-tracker-apps-iphone-mac/), [clockify.me](https://clockify.me/blog/productivity/best-habit-tracker-apps/)
- Widget and glanceable UX: [mindfulsuite.com](https://www.mindfulsuite.com/reviews/best-ios-widget-apps), [rapidnative.com](https://www.rapidnative.com/blogs/habit-tracker-calendar)
- AI chat interface design: [setproduct.com](https://www.setproduct.com/blog/ai-chat-interface-ui-design), [thefrontkit.com](https://thefrontkit.com/blogs/ai-chat-ui-best-practices)
- Agent UX patterns: [hatchworks.com](https://hatchworks.com/blog/ai-agents/agent-ux-patterns/)
- SSE vs polling vs WebSocket: [blog.openreplay.com](https://blog.openreplay.com/websockets-sse-long-polling/), [codelit.io](https://codelit.io/blog/websocket-vs-polling-vs-sse)
- PWA iOS limitations 2025-2026: [magicbell.com](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide), [mobiloud.com](https://www.mobiloud.com/blog/progressive-web-apps-ios)
- Web Push iOS 16.4: [pwa.io](https://pwa.io/articles/web-push-with-ios-safari-16-4-made-easy), [magicbell.com](https://www.magicbell.com/blog/using-push-notifications-in-pwas)
- PWA push reliability 2026: [edana.ch](https://edana.ch/en/2026/03/19/push-notifications-on-web-applications-pwa-is-it-really-reliable-on-ios-and-android/)
- Klaus design spec: `docs/superpowers/specs/2026-06-13-klaus-hub-design.md`
- Klaus project context: `.planning/PROJECT.md`

---
*Feature research for: Klaus Hub (v5.0) — web PWA personal interface*
*Researched: 2026-06-13*
