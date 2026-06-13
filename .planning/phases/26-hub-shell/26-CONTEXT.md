# Phase 26: Hub Shell - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

The web PWA **shell** — the foundation every later v5.0 phase builds on. Delivers:

- React + TypeScript + Vite PWA (Tailwind), built to static assets and served by FastAPI
  from the existing `klaus-agent` Cloud Run container (same origin, one deploy, no CORS),
  via a multi-stage Dockerfile (Node build stage).
- Google Sign-In allowlisted to Amit's account only → session cookie; all hub routes under
  `/api/*`; existing Telegram webhook / `/cron/*` / `/internal/*` / `/trigger/*` untouched.
- The **read-only Today timeline** (one `/api/today` endpoint composing calendar + leave-by/
  Get Ready + Garmin morning stats + weather + meals + training plan item + coach note +
  nutrition glance rail).
- A **chat MVP** — send + poll — sharing the existing Telegram Firestore conversation
  (one continuous Klaus), processed on the Cloud Tasks full-CPU path.
- Responsive layout: desktop = sidebar + timeline + glance rail + collapsible docked chat;
  phone = bottom tabs with Klaus as the center tab.
- PWA installability + offline app-shell (service worker) with skeletons + offline indicator.

**NOT in this phase** (later v5.0 phases): native Tasks (P27), Habits/supplements + habits
on the timeline / TIME-06 (P28), Web Push + Telegram-mirror flag (P29), Health pages (P30).
Tasks-on-glance-rail (TASK-07) and habits-on-timeline (TIME-06) are explicitly deferred to
their owning phases — the glance rail/timeline ship in P26 with the data sources that exist now.

**Visual styling / detailed layout is handled separately by `/gsd:ui-phase 26`** (UI hint = yes).
This CONTEXT.md captures product/behavior decisions, not pixel-level design.

</domain>

<decisions>
## Implementation Decisions

### Authentication & Session
- **D-01:** Auth model = **Google Sign-In allowlisted to Amit's account only + an effectively-permanent session.** Sign in once per device (iPhone + PC), then always-on in practice (long-lived cookie, silently refreshed on each visit). Rationale: the hub is on the public internet and the chat is a live command channel into Klaus (Gmail/calendar writes, LLM spend) — auth is non-optional. The allowlist already prevents anyone else's Google account from working; the permanent session gives the "it's just mine, always signed in" feel without recurring friction. Rejected: shared-secret link (leak-prone, no identity), no-auth (unacceptable exposure).
- **D-02:** **Sign-out + sign-out-everywhere.** A "Sign out" button clears this device's session, plus a "sign out everywhere" that invalidates all sessions server-side (lost-phone scenario). Implementation note: "revoke all" needs server-side session invalidation — a bumpable **session-version counter** (small Firestore doc or `UserProfileStore` field) is sufficient; it does NOT require the full Firestore-backed session store that HUBX-02 defers. In-process sessions remain acceptable for v5.0; the version counter is the one piece of server-side session state.

### Today Timeline — scope & behavior
- **D-03:** Timeline covers **strict today, midnight–midnight** (not rolling-24h, not now→EOD). Past items earlier today still render so the day reads as a whole; tomorrow is one tap away in the Calendar tab.
- **D-04:** **Now-line marker + past items dimmed/de-emphasized**, and **auto-scroll to the now-line on open**. Gives an at-a-glance "where am I in my day" read.
- **D-05:** Freshness = **refresh `/api/today` on open and on focus** (when the app regains foreground), plus **pull-to-refresh on phone**. No constant/timer polling — the timeline doesn't change second-to-second and Garmin/route lookups are not free.
- **D-06:** **Empty/not-yet-generated data → quiet "not ready yet" placeholder** (e.g. "Coach note coming after your morning briefing", "Sleep stats syncing…"). Distinct from in-flight network loading. **Planner note:** HUB-03's skeletons + offline indicator apply to *in-flight network fetches*; D-06 placeholders apply to *data that genuinely won't exist until later in the day* (coach note before the morning briefing, Garmin before sync). Both behaviors coexist — don't use a skeleton for data that will shimmer indefinitely.

### Klaus Chat (MVP)
- **D-07:** **One continuous conversation stream** — NOT ChatGPT/Claude-style multiple named threads. This matches the locked design: one Klaus, one shared Firestore history with Telegram (CHAT-01). Multi-thread would break the Telegram-shared-history invariant and fork Klaus's memory/context model. See Deferred Ideas for the someday-threads note.
- **D-08:** On open, load a **recent window (~30–50 messages)** for fast first paint, with **scroll-up to page in older history** from the shared Firestore conversation. Full backlog reachable by scrolling; nothing forked.
- **D-09:** Hub chat is processed via a **dedicated `/internal/process-hub-message` endpoint** on the Cloud Tasks full-CPU path. **Decision note / discrepancy resolved:** REQUIREMENTS CHAT-02 specifies a dedicated `/internal/process-hub-message`; the design-spec prose said reuse `/internal/process-update`. The locked requirement wins → build a dedicated hub endpoint (same full-CPU Cloud Tasks pattern as `/internal/process-update`, never a Starlette BackgroundTask per the CLAUDE.md invariant). The planner should decide how much of the existing process-update handler to share vs. duplicate.

### Unread badge (CHAT-04)
- **D-10:** Badge clears when you **scroll to the bottom** of the chat (newest message actually viewed) — not merely on tab open, not on app-focus-anywhere.
- **D-11:** Badge counts **all unseen Klaus messages** — direct replies AND proactive/autonomous-tick outreach AND anything that arrived via Telegram since last-seen. (Telegram-originated counting follows naturally from the shared history; full Telegram-mirror/push wiring is Phase 29.)

### PWA install onboarding (HUB-02)
- **D-12:** **One-time dismissible install banner.** When opened in Safari and not yet installed, show a small bottom banner with the iOS Share → Add to Home Screen steps; dismiss once and it stays gone (remembered locally). iOS has no `beforeinstallprompt`, so this is a manual-instruction nudge, not a programmatic prompt. Rejected: full onboarding screen (overkill for a twice-installed app), settings-only (too easy to miss).

### Claude's Discretion
- Service-worker caching strategy for HUB-03 (network-first for `index.html` so a stale cache never blocks a new deploy; cache-first for hashed/immutable assets) — standard approach, Claude decides specifics.
- Session cookie mechanics (signing, `httpOnly`/`Secure`/`SameSite`, refresh-on-visit implementation), Google Sign-In flow details (GIS button, popup vs redirect), and the exact session-version storage location.
- Frontend project structure, component breakdown, routing, state/data-fetching library choices.
- Optimistic-send + 2–3s polling implementation details for chat (behavior locked by CHAT-03; mechanics are Claude's).
- `/api/today` composition internals and caching of expensive sub-calls (routes/Garmin).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (locked source of truth)
- `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` — approved v5.0 design spec: layout (locked via mockups), architecture, auth model, chat plumbing, build-phase breakdown. **Note:** where its prose conflicts with REQUIREMENTS (the chat endpoint name), the requirement wins — see D-09.
- `.planning/REQUIREMENTS.md` — HUB-01..05, CHAT-01..04, TIME-01..05, TIME-07, TIME-08 (the 16 reqs this phase satisfies) + Out-of-Scope table (no streaming/WebSockets, no nutrition entry, etc.).
- `.planning/ROADMAP.md` § Phase 26 — goal + 6 success criteria.

### Backend integration points (existing code the shell wires into)
- `interfaces/web_server.py` — FastAPI app; existing routes (`/telegram-webhook`, `/internal/process-update`, all `/cron/*`, `/trigger/*`, `/health`). New `/api/*` + `/internal/process-hub-message` mount here; existing routes must stay untouched (HUB-04).
- `core/task_dispatch.py` — `enqueue_update()` Cloud Tasks → `/internal/process-update`. Model for hub-message dispatch (D-09).
- `memory/firestore_conversation.py` — the shared per-user conversation history (CHAT-01, chat load/append).
- `core/scheduled_message.py` — `send_and_inject()` (Telegram send + Firestore injection); relevant background for how messages enter the shared history.
- `core/auth_google.py` — existing Google OAuth/token patterns (reference for the sign-in/session work, though hub auth is a session cookie, not the agent's Google tokens).
- `mcp_tools/routes_tool.py` — traffic-aware drive time, for timeline leave-by / Get Ready (TIME-05).
- `mcp_tools/calendar_tool.py`, `mcp_tools/weather_tool.py`, `mcp_tools/garmin_tool.py` — calendar events, weather one-liner, Garmin morning stats for `/api/today`.
- `memory/firestore_db.py` — `MealStore.get_day` (meals as slot labels + nutrition glance totals; **slot-time caveat: never infer eating time**), `UserProfileStore` (training plan item + block context "Week N of 16"), and the `_jsonsafe_doc` helper (ISO-convert `DatetimeWithNanoseconds` before `json.dumps`).
- `Dockerfile` — currently single-stage `python:3.11-slim`, single uvicorn worker (in-process `ConversationManager` requires `--workers 1`). Phase 26 makes it multi-stage (Node build → copy `dist` into the Python image).

### Project invariants (must-read constraints)
- `CLAUDE.md` § 6 Invariants — single-worker requirement, agent turns must run inside a tracked Cloud Tasks request (never Starlette BackgroundTask), lowercase `klaus-` resource naming, `load_dotenv(override=True)`, explicit LLM timeouts, slot-time caveat.
- `.planning/STATE.md` § Accumulated Context / Decisions — the v5.0 design decisions already locked (served same-origin, `/api/*` auth, shared Firestore chat, display-only nutrition, multi-stage Dockerfile, phase independence).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/task_dispatch.py::enqueue_update` — copy/adapt for hub-message enqueue to `/internal/process-hub-message`.
- `/internal/process-update` handler in `interfaces/web_server.py` — the full-CPU turn-processing pattern to mirror for hub messages.
- `memory/firestore_conversation.py` — read recent window + paginate older; append hub-sent messages. Already the single source Telegram uses.
- `memory/firestore_db.py` stores + `_jsonsafe_doc` — `/api/today` data sources; reuse the JSON-safe serialization helper for every read tool/route.
- `mcp_tools/{calendar,weather,garmin,routes}_tool.py` — already encapsulate the external calls `/api/today` needs.

### Established Patterns
- FastAPI route registration in `interfaces/web_server.py`; `/cron/*` use OIDC, `/internal/*` use Cloud Tasks OIDC — `/api/*` introduces a NEW auth pattern (session cookie) that must NOT weaken the existing OIDC routes.
- Single uvicorn worker + in-process `ConversationManager` — frontend must be served as static files from the same single-worker process (no separate frontend server).
- Firestore `SERVER_TIMESTAMP` reads back as `DatetimeWithNanoseconds` → ISO-convert before `json.dumps` in every `/api/*` JSON response.

### Integration Points
- Static-asset serving: built Vite `dist/` mounted under the FastAPI app (SPA fallback to `index.html`), without shadowing `/api/*`, `/cron/*`, `/internal/*`, `/trigger/*`, `/telegram-webhook`, `/health`.
- Multi-stage Dockerfile: Node stage builds the frontend; Python stage copies `dist/` and runs uvicorn (still `--workers 1`).
- Cloud Tasks queue (existing, region `me-central1`) gains a second target URL (`/internal/process-hub-message`) or reuses the queue with a different path.

</code_context>

<specifics>
## Specific Ideas

- Amit wants the hub to *feel* like "it's just mine and always on" — the permanent-session + once-per-device sign-in (D-01) is the concrete expression of that. Do not introduce recurring login friction.
- Amit raised wanting a ChatGPT/Claude-style "new chat + sidebar" experience; after discussion he accepted the one-continuous-stream model (D-07) because it preserves the one-Klaus / Telegram-shared-history design. Captured as a deferred idea, not dropped.
- Timeline should read as "where am I in my day right now" (now-line + auto-scroll, D-04) rather than a static agenda list.

</specifics>

<deferred>
## Deferred Ideas

- **ChatGPT/Claude-style multi-conversation threads** (new-chat + sidebar of past chats) — would require rethinking the single-shared-Telegram-history design (CHAT-01) and Klaus's continuous-conversation memory model. Someday/v2 exploration; out of scope for v5.0. Related: HUBX-01 (SSE streaming), HUBX-02 (Firestore-backed sessions).
- **Tasks on glance rail / Today timeline (TASK-07)** — depends on `TaskStore`; lives in Phase 27.
- **Habits/supplements on the timeline (TIME-06)** — depends on `HabitStore`; lives in Phase 28.
- **Web Push + Telegram-mirror flag + unread-count app-icon badge (PUSH-01..04)** — Phase 29. (P26 ships the in-app unread badge per CHAT-04 / D-10/D-11; the OS-level Badging API is Phase 29.)
- **Periodic auto-refresh / SSE for the timeline and chat** — only if refresh-on-focus + polling proves insufficient in real use (HUBX-01).

</deferred>

---

*Phase: 26-Hub Shell*
*Context gathered: 2026-06-13*
