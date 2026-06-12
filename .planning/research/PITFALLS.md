# Pitfalls Research

**Domain:** Adding a PWA hub + Web Push + dual-interface chat to an existing FastAPI/Cloud Run personal agent (Klaus v5.0)
**Researched:** 2026-06-13
**Confidence:** HIGH — analysis drawn from the live codebase, approved design spec, known shipped incidents (slow-reply 2026-06-12), and verified external sources on iOS Push, Firestore billing, and FastAPI/SPA integration patterns

---

## Critical Pitfalls

### Pitfall 1: iOS Web Push — Permission Not Triggered from a User Gesture

**What goes wrong:**
The VAPID push permission dialog on iOS Safari never appears, or appears and is immediately dismissed as invalid. iOS requires `Notification.requestPermission()` to be called directly from within a click/tap handler — not from a `setTimeout`, `useEffect` on mount, or any async callback chain that breaks the user-gesture requirement. If the permission request is deferred even one microtask tick outside the direct handler, Safari silently drops it. Additionally, the push subscription only works when the PWA is installed to the home screen via Share → Add to Home Screen on iOS 16.4+; opening the URL in Safari browser does not support Web Push.

**Why it happens:**
Developers test in Chrome (desktop or Android) where the user-gesture requirement is looser. The "enable notifications" flow in the shell phase is often wired to a React `useEffect` or a post-login callback, both of which break the iOS gesture chain. The installed-PWA-only constraint is missed because the PWA still renders fine in Safari browser — the push subscription call just fails silently.

**How to avoid:**
- Wire the permission request to a dedicated "Enable Notifications" button click handler — never to mount, auth callback, or any async path.
- At subscription time, check `window.matchMedia('(display-mode: standalone)').matches` or `navigator.standalone`; if false on iOS, show a prompt guiding the user to install the PWA before enabling push. Do not silently attempt and fail.
- Test the full push flow on a physical iPhone with the app installed, not in Safari browser or Chrome devtools.
- Add a visible badge/indicator in the hub showing push status (active / not installed / permission denied) so silent failures are surfaced.

**Warning signs:**
- Notification permission dialog never appears on iPhone after clicking "Enable."
- `PushManager.subscribe()` throws `NotAllowedError` with no user gesture in the call stack.
- Chrome desktop push works; iPhone push does not.
- Push subscription is stored in `PushSubscriptionStore` but no notification arrives on iPhone.

**Phase to address:**
Phase 4 (Web Push). The gesture requirement must be built into the Phase 4 permission UI design — not retrofitted after the UI is already wired.

---

### Pitfall 2: iOS Web Push — Silent Subscription Termination Without `event.waitUntil()`

**What goes wrong:**
Push notifications arrive on desktop and Android, but on iPhone the service worker receives the push event, processes it, and then Safari silently revokes the push notification permission — terminating future pushes entirely. No 410 error is returned; the subscription appears valid in `PushSubscriptionStore`. The root cause: Safari requires that every push event immediately display a visible notification. If the push event handler does any async work (fetching data, reading IndexedDB) before calling `showNotification()`, and that work is not wrapped in `event.waitUntil()`, Safari treats it as a "silent push" (which iOS does not support) and revokes the subscription.

**Why it happens:**
The service worker push handler calls `event.waitUntil(somePromise)` where `somePromise` resolves without calling `self.registration.showNotification()`, or the promise is structured so that notification display is conditional. iOS enforces the "must show a notification" rule strictly — any conditional or delayed display triggers revocation. Unlike Android and desktop, iOS has no "silent push" budget.

**How to avoid:**
- The push event handler must call `event.waitUntil(self.registration.showNotification(...))` synchronously from within the push handler before any awaited async call.
- Never make the `showNotification()` call conditional based on fetched data; instead, show a notification immediately with whatever data is in the push payload, and optionally update it after async enrichment.
- Design the push payload to be self-contained (title + body in the VAPID payload itself) — do not rely on a subsequent fetch to determine what to show.
- Add a smoke test: send a push with an intentionally async handler and verify the subscription is not revoked on iPhone after 3 pushes.

**Warning signs:**
- First 2-3 push notifications arrive on iPhone, then pushes stop silently.
- `PushSubscriptionStore` still shows a valid subscription for the device.
- Sending a push returns HTTP 201 from APNs (success), but no notification appears.
- iOS revokes the permission — the hub's push status indicator shows "permission denied" after previously being active.

**Phase to address:**
Phase 4 (Web Push). The service worker push handler skeleton must be written and tested on iPhone before any push delivery logic is wired to the autonomous tick or `scheduled_message.py`.

---

### Pitfall 3: Web Push Subscription Expiry and 410 Gone — No Resubscription Path

**What goes wrong:**
After days or weeks, the push service returns HTTP 410 (Gone) or 404 for a previously valid VAPID subscription. The server-side push delivery fails, but `PushSubscriptionStore` retains the dead subscription. Future pushes all fail silently. The hub shows Klaus's messages only when actively open, with no notification when closed — the core value of Phase 4 is broken without any visible error.

**Why it happens:**
Browser push subscriptions can expire or be invalidated when the user reinstalls the PWA, clears browser data, or when APNs (Apple's push infrastructure for iOS) rotates the endpoint. Safari specifically does not expose `expirationTime` on the subscription object, unlike Chrome, so there is no proactive warning. The common mistake is to treat a stored subscription as permanently valid and not handle 410/404 responses from the push service.

**How to avoid:**
- In the Python push-delivery function (added to `scheduled_message.py` and the autonomous tick path), handle HTTP 410 and 404 responses by deleting the subscription from `PushSubscriptionStore` and logging a warning — do not treat them as transient errors.
- The hub frontend must recheck push subscription validity on each app open and resubscribe automatically if the stored subscription is gone — wrap this in the same "Enable Notifications" gesture flow.
- Add a `last_used_at` and `last_delivery_status` field to `PushSubscriptionStore` so the health page can show "last push delivered N days ago."
- Do not store multiple subscriptions for the same device without a clear update path — overwrite on resubscribe using a device fingerprint key.

**Warning signs:**
- Push delivery returns 410 from APNs in server logs but `PushSubscriptionStore` is not cleaned up.
- Hub shows push status as "active" but no notification has arrived in several days.
- After reinstalling the PWA, push stops working until manually re-enabling in settings.

**Phase to address:**
Phase 4 (Web Push). 410 handling in the delivery path and resubscription on app open are both Phase 4 requirements, not optional polish.

---

### Pitfall 4: Service Worker Cache Poisoning — Stale `index.html` After Cloud Run Revision Change

**What goes wrong:**
A new Cloud Run revision is deployed with updated JS bundles. The hub's service worker has cached `index.html` from the previous revision. When Amit opens the hub, the old `index.html` loads, references asset hashes that no longer exist at the new revision's URLs, and the app fails with network errors or renders a broken shell. This is especially damaging on iPhone where the installed PWA's shell is what the service worker serves offline — a poisoned cache means the app is broken even when online.

**Why it happens:**
FastAPI (or Cloud Run's load balancer) does not set `Cache-Control: no-cache` on `index.html` by default. The browser and the service worker both cache it aggressively. Vite hashes JS/CSS asset filenames for cache-busting, but `index.html` is always at the same URL. If the service worker caches `index.html` with `max-age`, it will not re-fetch it after a deploy.

**How to avoid:**
- Serve `index.html` with `Cache-Control: no-cache, no-store, must-revalidate` from FastAPI — never let it be cached by CDN, browser, or service worker. Add this explicitly to the route that serves the SPA fallback.
- In the Vite PWA plugin (vite-plugin-pwa / Workbox), exclude `index.html` from the precache manifest. All other assets (JS, CSS, images) can use Workbox's asset hashing strategy.
- Use `registerType: 'prompt'` in vite-plugin-pwa so that when a new service worker is waiting, the hub shows an "Update available" prompt — never use `autoUpdate` with `skipWaiting: true` unless you have tested that it does not break mid-session state.
- Add a deploy smoke test: after each revision, open the hub on iPhone and verify the correct version is shown.

**Warning signs:**
- After a deploy, the hub loads but shows JS errors about missing chunks or undefined exports.
- The version string shown in the hub (if present) is from the previous deploy.
- Vite dev tools show the service worker is "waiting" indefinitely after a deploy.
- The app works in Chrome (which skips the service worker in incognito) but not in the installed iPhone PWA.

**Phase to address:**
Phase 1 (Shell). The `Cache-Control: no-cache` header for `index.html` and the service worker precache config must be set during the initial shell build — before any caching strategy is added.

---

### Pitfall 5: SPA Fallback Route Shadowing Existing Webhook, Cron, and Internal Routes

**What goes wrong:**
A catch-all route `GET /{full_path:path}` returning `index.html` is added to `web_server.py` to support React Router. This route, if defined before or at the same level as `/webhook/telegram`, `/cron/*`, `/internal/process-update`, or `/trigger/*`, begins intercepting those requests and returning HTML instead of the expected JSON — breaking Telegram webhook delivery, Cloud Scheduler OIDC-authenticated cron calls, and the Cloud Tasks callback that runs agent turns. The result can be silent: Telegram stops delivering updates (webhook returns 200 with HTML, Telegram interprets it as success), while cron jobs fail with parse errors.

**Why it happens:**
FastAPI route matching is first-match-wins. `app.get("/{full_path:path}")` matches everything, including `/webhook/telegram`. If it is registered before the specific routes (or if the specific routes are in an `APIRouter` included after the catch-all), the catch-all wins. The mistake is also common when using `app.mount("/", StaticFiles(...))` which acts as a sub-application and does not apply FastAPI's route ordering rules.

**How to avoid:**
- Define all API-side routes — Telegram webhook, `/cron/*`, `/internal/*`, `/trigger/*`, `/api/*` — before registering the SPA catch-all route. In `web_server.py`, the catch-all must be the absolute last route.
- Do not use `app.mount("/", StaticFiles(...))` for the SPA fallback; use a `@app.get("/{full_path:path}")` route handler that manually checks if the path is an existing static asset (returns it), or falls back to `index.html`. This keeps the route in the FastAPI router where ordering is respected.
- Add a smoke test: after the SPA is wired up, POST a synthetic Telegram update to `/webhook/telegram` and verify it returns the expected `{"ok": true}` response, not HTML.
- Add a smoke test for `/internal/process-update` and one cron endpoint from Cloud Scheduler. These are the most critical paths that must not be shadowed.

**Warning signs:**
- Telegram stops delivering messages after the SPA shell is deployed.
- Cloud Scheduler job shows "200" responses but cron logic is not executing.
- `/internal/process-update` returns 200 but agent turns are not completing — check Content-Type in the response.
- `curl -X POST /webhook/telegram` returns HTML `<!DOCTYPE html>` instead of JSON.

**Phase to address:**
Phase 1 (Shell). The catch-all must be designed correctly from the first commit that serves the SPA — not retrofitted after Telegram breaks in production.

---

### Pitfall 6: Hub Session Cookie Auth Conflicting with OIDC Cron Auth

**What goes wrong:**
Phase 1 adds `SessionMiddleware` to `web_server.py` for Google Sign-In cookie auth. The existing `/cron/*` routes use OIDC token validation (the Cloud Scheduler service account's Bearer token in the `Authorization` header). After adding `SessionMiddleware`, one of two failures occurs:
1. The session middleware strips or modifies the `Authorization` header before the OIDC validator reads it, causing all cron calls to fail with 401.
2. The SPA auth adds `SameSite=Lax` or `SameSite=Strict` cookies that the Cloud Scheduler service account does not send, and the cron validator is accidentally changed to require the session cookie instead of the OIDC token — locking out all crons.

A subtler version: the `starlette-session` or `itsdangerous` session middleware raises an exception on requests that do not have a valid session cookie (cron calls), breaking the OIDC path entirely if the exception is not narrowed to hub routes only.

**Why it happens:**
Middleware in Starlette/FastAPI is global by default — it runs on every request including cron and webhook routes. Session middleware is often configured for the whole app during development, then left that way in production. The OIDC validator and the session validator use different auth channels (`Authorization` header vs. cookie) and must not interfere, but without explicit scoping they do.

**How to avoid:**
- Apply `SessionMiddleware` only to the `/api/*` route prefix using a sub-application or explicit path check in the middleware, not globally.
- Keep the OIDC cron validator as the first handler in `/cron/*` routes; it must read `Authorization: Bearer` and must not depend on a session cookie being present or absent.
- Separate auth concerns in code: `auth_google.py` for OIDC (existing, do not modify), and a new `auth_hub.py` for session cookie management — never merge them into the same middleware stack.
- After adding session middleware, run the full cron smoke test: POST to a cron endpoint with a valid OIDC token and verify it still succeeds.

**Warning signs:**
- All cron jobs begin returning 401 after the session middleware is added.
- `POST /webhook/telegram` returns 403 after the session middleware is added.
- The hub login works but `/cron/morning-briefing` returns a session-related error.
- Cloud Scheduler job history shows a sudden spike in failures on the same day the session middleware was deployed.

**Phase to address:**
Phase 1 (Shell). The auth middleware design must scope session auth to `/api/*` routes from day one — this cannot be corrected easily after the fact without a full middleware refactor.

---

### Pitfall 7: Dual-Interface Chat — Double Replies and the Telegram Mirror Race

**What goes wrong:**
A message sent from the hub triggers the Cloud Tasks agent turn via `/api/chat` → `task_dispatch.py` → `/internal/process-update`. The agent composes a reply and calls `scheduled_message.py` to deliver it. With the Telegram mirror flag enabled (Phase 4 hybrid transition), `scheduled_message.py` sends the reply both to the hub (via Web Push + Firestore injection) and to Telegram. If Amit simultaneously sends a message via Telegram (which also goes through `/internal/process-update`), two agent turns are in flight. The shared Firestore conversation history gets both replies injected. The hub's polling sees both messages; Telegram delivers both. Result: duplicate or interleaved replies that make Klaus appear incoherent.

The subtler version: the hub polls the Firestore conversation every N seconds. A new reply arrives. The autonomous tick fires concurrently and also injects a message. The hub shows Klaus's proactive message and the reply in a race-determined order, breaking the conversational thread.

**Why it happens:**
The existing Firestore conversation is a single shared document (`firestore_conversation.py`) used by both Telegram and the hub. It was designed for a single-interface world. There is no turn-level mutex — the `_get_orchestrator()` singleton prevents parallel agent instantiation within one Cloud Run instance, but Cloud Tasks enqueues can arrive at different Cloud Run instances and both proceed in parallel.

**How to avoid:**
- Add a `source` field to each message in the Firestore conversation: `"telegram"` or `"hub"`. The hub's UI renders all messages from either source, but the reply routing in `scheduled_message.py` must check which source the triggering message came from and deliver the reply to that source first (push + Firestore), then mirror to Telegram only if the mirror flag is enabled.
- Use a `turn_lock` document in Firestore (with a TTL) to prevent two concurrent agent turns on the same conversation. Before enqueuing in `task_dispatch.py`, write the lock; after the turn completes, delete it. If the lock exists when a new turn would be enqueued, queue the new message for processing after the current turn.
- For the hub's polling, filter on `created_at > last_seen_timestamp` client-side and use a stable sort by `created_at` — do not rely on Firestore insertion order.

**Warning signs:**
- Amit sends a message from the hub and a response appears twice — once from the hub reply path and once from the Telegram mirror.
- The hub chat shows messages in a different order than Telegram.
- The conversation history in Firestore has two consecutive assistant messages with different content.
- After enabling the Telegram mirror flag, proactive autonomous tick messages appear in the hub with a duplicate in Telegram within seconds of each other.

**Phase to address:**
Phase 1 (Shell) must introduce the `source` field on messages. The turn-lock mechanism is Phase 4 (Web Push / dual delivery) where the mirror flag is activated.

---

### Pitfall 8: Hub Polling Firestore — Cost Blowup From Aggressive Polling Interval

**What goes wrong:**
The hub polls `/api/messages` (backed by a Firestore read of the conversation collection) every few seconds while the tab is open. At a 3-second interval, one open browser tab generates 20 Firestore document reads per minute. Multiply by an active session of 30 minutes: 600 reads for one conversation. Firestore charges $0.06 per 100,000 reads on Cloud Firestore native mode, which is low at single-user scale — but the real cost is bandwidth and latency, not billing. The more dangerous failure mode: the polling is implemented as a full conversation collection fetch (all messages, not just new ones since last poll), which re-reads N documents on every tick and scales with conversation length.

**Why it happens:**
Polling is simple to implement; the mistake is fetching the entire conversation document on each poll rather than querying only for messages newer than the last-seen ID. In Firestore, a query with `where('created_at', '>', last_seen)` reads only the new documents, not the entire history.

**How to avoid:**
- Implement polling with a `?since=<ISO timestamp>` parameter on `/api/messages`. The Firestore query must use `where('created_at', '>', last_seen)` and `order_by('created_at')` — Firestore will need a composite index on `(conversation_id, created_at)`.
- Use exponential backoff during quiet periods: if no new messages arrive in 30 seconds, extend the poll interval to 10s, then 30s. Reset to fast polling (3s) when a message is sent or received.
- For Phase 4+, replace polling with SSE (Server-Sent Events) on a `/api/messages/stream` endpoint — one long-lived connection, zero poll overhead. Phase 1 polling is acceptable as a known v1 tradeoff, documented for Phase 4 replacement.
- Add a Firestore composite index for `(user_id, created_at DESC)` on the conversation collection during Phase 1 — the polling query will require it and without it Firestore will refuse the query or full-scan.

**Warning signs:**
- Firestore read count in the GCP billing dashboard spikes after the hub is opened.
- Hub `GET /api/messages` requests appear at constant 3-second intervals in Cloud Run request logs even when no messages have been sent.
- Hub chat feels slow on mobile because each poll is re-fetching a growing conversation history.

**Phase to address:**
Phase 1 (Shell). The `?since=` parameter and bounded query must be built from the start. The Firestore composite index must be created before Phase 1 UAT.

---

### Pitfall 9: Cloud Run Cold Start vs. Service Worker Offline Shell Expectations

**What goes wrong:**
The installed PWA on iPhone has a service worker that serves the app shell (HTML + JS) from cache when offline, which is correct. However, users expect that "offline" means full functionality — they tap a task, expect it to save, and get a network error. Worse: the hub opens instantly from the service worker cache, but the first API call (`/api/today`, `/api/messages`) hits a cold Cloud Run instance with a 2-8 second cold start. The user sees a blank "Loading..." state for several seconds after the shell renders, creating the impression the app is broken.

The flip side: during a Cloud Run cold start, the service worker may intercept the API calls and return a cached stale response from a previous session (tasks from yesterday, an old conversation state) if the service worker caching strategy is too aggressive.

**Why it happens:**
Vite PWA plugin's Workbox default strategy caches all same-origin requests. Without explicit runtime caching rules, API responses under `/api/*` get cached indefinitely. On next open, the stale cached API response is returned instead of the live Firestore data. The developer tests on a warm instance and never sees the cold start latency.

**How to avoid:**
- Exclude all `/api/*` routes from Workbox runtime caching — API responses must always be network-first, never cached. Configure `runtimeCaching` in the Workbox config to explicitly allow caching only for static assets (images, fonts, the built JS/CSS).
- For the app shell itself: cache-first for the built static assets (already handled by Vite's asset hashing), network-first (with cache fallback) for `index.html`.
- Handle cold start latency in the UI with skeleton loaders (not blank screens) so the perceived performance is acceptable. Design the `/api/today` response to return a partial result quickly rather than waiting for all data sources to resolve.
- Set Cloud Run minimum instances to 1 for the `me-west1` service (already at minimum 1 for the Telegram webhook to be responsive) — this eliminates the cold start for the primary use case.

**Warning signs:**
- The hub shows yesterday's tasks on open, then the correct tasks appear after a few seconds (stale cache being replaced).
- API calls in the service worker logs are served from `(ServiceWorker)` cache instead of the network.
- The hub works perfectly in Chrome devtools (which can disable the service worker) but serves stale data in the installed iPhone PWA.
- Cold start latency visible in Cloud Run logs correlates with "blank screen for 5 seconds" UX reports.

**Phase to address:**
Phase 1 (Shell). The Workbox runtime caching configuration for `/api/*` exclusion must be done before the first live deploy. The skeleton loader UX is also Phase 1.

---

### Pitfall 10: TickTick Import — Recurrence Mapping and Timezone Misalignment

**What goes wrong:**
The one-time TickTick import script (Phase 2) pulls tasks via the TickTick Open API (already have `mcp_tools/ticktick_tool.py` + `ticktick_auth.py`). TickTick stores recurring tasks with RRULE strings (e.g., `RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR`) and per-task timezone fields. `TaskStore` only needs to support "simple recurrence" per the design spec. The import fails silently: tasks with complex RRULE patterns (e.g., `UNTIL=`, `COUNT=`, `BYDAY` with ordinals like `2MO` for "second Monday") are imported without recurrence (become one-off tasks) because the mapping logic doesn't handle them — and Amit doesn't notice until a recurring task he relied on never appears.

The timezone issue: TickTick stores task due times in the task's `timeZone` field, which may differ from `Asia/Jerusalem`. The import naively converts `dueDate` to UTC, then the hub displays it in `Asia/Jerusalem`, which shifts the due time by 2-3 hours (or straddles midnight and becomes a different day during DST transitions).

**Why it happens:**
RRULE is a rich spec; "simple recurrence" implementations typically handle `FREQ=DAILY/WEEKLY/MONTHLY` without modifiers. The import script handles the common case in smoke testing but misses the edge cases that are common in a real task list built over years. Timezone conversion is done with `datetime.utcnow()` instead of aware datetimes, losing the original `timeZone` context.

**How to avoid:**
- Before writing any import logic, export Amit's full TickTick task list and audit the RRULE patterns present. This takes 30 minutes and prevents scope surprise during Phase 2.
- Define `TaskStore` recurrence as a union type that covers the actually-present patterns, not just a theoretical minimum. If `BYDAY=MO,WE,FR` appears in the export, support it; if complex ordinals (`2MO`) appear rarely, import them as "manual review needed" with a comment field rather than silently dropping the recurrence.
- All TickTick `dueDate` values must be converted using the task's own `timeZone` field: `datetime.fromisoformat(due_date).replace(tzinfo=ZoneInfo(task["timeZone"]))`. Store in Firestore as UTC; display in the hub converted to `Asia/Jerusalem` via `ZoneInfo("Asia/Jerusalem")`.
- The import script must output a reconciliation report: N tasks imported cleanly, N with recurrence downgraded (list titles), N with timezone warnings. Amit reviews before cancelling the TickTick subscription.

**Warning signs:**
- Recurring tasks appear in `TaskStore` as single-occurrence tasks with a `due` date in the past.
- Due times are off by 2-3 hours after import.
- The reconciliation report is absent — no visibility into what was lost.
- Amit notices a specific recurring task is missing only after cancelling TickTick.

**Phase to address:**
Phase 2 (Tasks). The RRULE audit of Amit's export must be the first step of Phase 2, before any `TaskStore` schema is finalized.

---

### Pitfall 11: Habit Streak Timezone — Asia/Jerusalem DST and Midnight Rollover

**What goes wrong:**
Habit streaks are computed by checking whether a completion log entry exists for "today." If "today" is computed in UTC, the day boundary is 02:00 local time in winter (UTC+2) and 03:00 in summer (UTC+3 during Israel DST). A completion logged at 23:45 local time on a Tuesday is stored with a UTC timestamp of 21:45 (UTC+2 winter) or 20:45 (UTC+3 summer). If the streak query compares UTC dates, it may assign this completion to Tuesday in UTC but Wednesday in local time — or vice versa — breaking the streak count.

The Israel DST transition (which does not follow the standard EU/US schedule) creates an additional edge case: Israel DST switches on specific Fridays before Jewish holidays, not on standard last-Sunday dates. A completion logged near the DST boundary may shift by an hour relative to the streak computation.

**Why it happens:**
Streak logic uses Python `datetime.utcnow().date()` for "today" — a common mistake when the user is not in UTC. Firestore timestamps are stored as UTC (correct), but the date comparison for streak purposes must use `Asia/Jerusalem` midnight as the day boundary, not UTC midnight.

**How to avoid:**
- All streak computation must use `datetime.now(ZoneInfo("Asia/Jerusalem")).date()` as "today." This is the single authoritative day boundary for all habit/supplement logic.
- Completion timestamps are stored as UTC in Firestore (consistent with all other stores), but streak queries convert to `Asia/Jerusalem` before comparing dates.
- Add a `compute_streak(completions: List[datetime], tz: str = "Asia/Jerusalem") -> int` pure function in `memory/firestore_db.py` that is tested against DST edge cases — both the standard Israel spring-forward and the pre-holiday schedule.
- The daily habit reset (which marks "today's" habits as pending) must fire after `Asia/Jerusalem` midnight — either at 00:05 IST via a cron or as a computed "is today already logged?" check at read time.

**Warning signs:**
- Streak resets unexpectedly for completions logged late at night (23:00-23:59 IST).
- During Israel DST transition weekends, all streaks reset even for users who completed habits.
- The hub shows "0 day streak" on Friday morning despite a completion on Thursday evening.
- Habit completion timestamps in Firestore are 2-3 hours off from when the check-off was tapped.

**Phase to address:**
Phase 3 (Habits). The `compute_streak` pure function with timezone handling must be implemented and unit-tested with DST edge cases before any streak is displayed in the hub UI.

---

### Pitfall 12: Agent Turn Must Use Cloud Tasks — Not a Hub Background Task

**What goes wrong:**
The hub's `/api/chat` endpoint receives a message and dispatches the agent turn. The temptation is to use FastAPI's `BackgroundTasks` (`background_tasks.add_task(run_agent, ...)`) instead of enqueuing via `core/task_dispatch.py`. This appears to work locally and in warm Cloud Run instances, but under the default Cloud Run CPU-throttling model, the background task runs after the response is returned — at which point Cloud Run throttles the CPU. The agent turn hangs, LLM calls time out, and the reply never arrives. This is exactly the incident that occurred on 2026-06-12 (18-minute reply, fixed by moving Telegram turns to Cloud Tasks). Repeating the same mistake for the hub would re-introduce the same failure.

**Why it happens:**
`BackgroundTasks` is convenient and well-documented in FastAPI. The Cloud Run CPU throttle behavior is non-obvious and only manifests under production CPU allocation settings, not locally. The fix (Cloud Tasks dispatch) requires more infrastructure (queue name, Cloud Tasks client, internal endpoint) and developers skip it for the "simpler" path.

**How to avoid:**
- The hub `/api/chat` endpoint must follow the exact same pattern as the Telegram webhook: return `{"ok": true}` immediately, enqueue via `core/task_dispatch.py` to `/internal/process-update`, let the Cloud Tasks call carry the turn on full CPU. No exceptions.
- Do not add any new `BackgroundTasks` usage to `web_server.py` for any agent-related work. This invariant is already in `CLAUDE.md` ("Agent turns must run INSIDE a tracked request") — enforce it explicitly in code review for every Phase 1 PR.
- The Cloud Tasks queue (`me-central1`, `queue: ...`) is already configured for Telegram turns. The hub can use the same queue with a `source: "hub"` field in the task payload so the `/internal/process-update` handler knows where to route the reply.

**Warning signs:**
- `/api/chat` uses `background_tasks.add_task` anywhere in the implementation.
- Agent replies take 15+ seconds in production but are fast locally.
- Cloud Run request logs show the `/api/chat` request completing quickly but no subsequent `/internal/process-update` request appearing.
- Hub chat shows "thinking..." indefinitely after a message is sent.

**Phase to address:**
Phase 1 (Shell). The Cloud Tasks dispatch path for `/api/chat` must be designed in Phase 1 before any chat UI is wired. The invariant must be documented in the Phase 1 implementation notes.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Serving `index.html` without `Cache-Control: no-cache` | Zero config | Stale app shell after every deploy; requires users to manually clear cache | Never — set the header from day one |
| Global `SessionMiddleware` applied to all routes | Simple auth setup | Breaks OIDC cron auth and Telegram webhook; requires full middleware refactor to fix | Never — scope to `/api/*` from the start |
| Polling entire conversation on each tick vs. `?since=` query | Simpler implementation | Scales with conversation length; breaks at long conversation histories | Acceptable only in a 1-week Phase 1 spike; must be replaced before Phase 4 |
| Using `BackgroundTasks` for agent turns instead of Cloud Tasks | Simpler code | Reproduces the 2026-06-12 18-minute reply incident under CPU throttle | Never — Cloud Run CPU throttle makes this category error |
| TickTick import without a reconciliation report | Faster to write | Amit unknowingly loses recurring tasks or incorrect due times; can't cancel TickTick with confidence | Never — the report is what makes the import trustworthy |
| Streak computation in UTC midnight instead of `Asia/Jerusalem` midnight | One less import | Streak resets near midnight local time; DST transitions corrupt all streaks | Never — the timezone is known at design time |
| Caching `/api/*` responses in Workbox runtime cache | Instant repeat-visit data | Stale tasks/habits/messages shown from cache instead of live Firestore data | Never — API routes must be network-first |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| iOS Web Push + Safari | Calling `requestPermission()` from `useEffect` or auth callback | Call only from a direct button click handler; check `navigator.standalone` before subscribing |
| iOS Web Push + APNs | Treating 201 from APNs as proof of delivery | 201 means accepted; actual delivery to device is not confirmed. Handle 410/404 by deleting the subscription |
| Firestore conversation + dual interface | Reading all messages on every hub poll | Query `where('created_at', '>', last_seen)` — requires a composite index on `(user_id, created_at)` |
| FastAPI StaticFiles + SPA fallback | `app.mount("/", StaticFiles(...))` shadowing API routes | Use `@app.get("/{full_path:path}")` handler last, after all API and webhook routes are registered |
| TickTick API + timezone | Converting `dueDate` to UTC using `datetime.utcnow()` | Parse with `ZoneInfo(task["timeZone"])` from the task's own timezone field |
| Cloud Run + service worker | Workbox caching `/api/*` responses | Explicitly exclude `/api/**` from all Workbox `runtimeCaching` entries |
| `scheduled_message.py` + Telegram mirror | Both hub and Telegram delivery happen in the same function, no `source` routing | Check `source` field on the triggering message; deliver to source first, then mirror if flag is set |
| `HabitStore` streak + Firestore timestamps | Comparing Firestore UTC timestamps with Python `datetime.date()` (UTC) for day boundaries | Always convert to `ZoneInfo("Asia/Jerusalem")` before `.date()` comparison |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Hub polling at constant 3s interval regardless of activity | Sustained Firestore read traffic in Cloud Run logs during all waking hours | Implement exponential backoff; reset on send/receive | From day one of Phase 1 UAT |
| `/api/today` fetching all data sources sequentially | 6-10 second load time on first hub open | `asyncio.gather()` for independent sources (calendar, MealStore, HabitStore, Garmin, weather) | First load after Phase 1 deploy |
| Full conversation collection scan on each poll | Poll latency grows linearly with conversation history | `?since=` query with Firestore composite index | After ~200 messages in history |
| No `Cache-Control: no-cache` on `index.html` | Old JS bundle runs after a deploy; manifest.json mismatches | Set the header in FastAPI before the first deploy | Every deploy after the first |
| Autonomous tick `Layer-0` gather adding HabitStore read | Tick gather latency increases for every new store added without parallelism | Fan-out habit store read alongside existing Layer-0 reads using the existing thread pool pattern (see `core/autonomous.py`) | After Phase 3 ships habits into the tick |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Session cookie without `HttpOnly` + `Secure` + `SameSite=Lax` | JavaScript-readable cookie; susceptible to CSRF | Set all three attributes explicitly in the session cookie configuration |
| `/api/*` routes that check session cookie but not that the `sub` claim matches Amit's Google account ID | Another Google account could log in if the OAuth client is misconfigured | Validate `sub` or `email` against a hard-coded allowlist (`ALLOWED_GOOGLE_ACCOUNTS` env var) in every `/api/*` route |
| VAPID private key stored in `.env` / Secret Manager but logged in error traces | Key exposure allows anyone to send pushes as Klaus | Treat VAPID private key with same sensitivity as `TELEGRAM_BOT_TOKEN`; add to the `self_inspect.py` secret denylist |
| Push subscription endpoint stored in plaintext Firestore without any access control | Push subscriptions are single-use URLs that allow targeted push delivery | `PushSubscriptionStore` collection must use Firestore security rules or be accessible only via the server-side Python client, never from client JS directly |
| Google OAuth redirect URI allowing arbitrary state parameter | Open-redirect attack during login | Validate the `state` parameter is a known value (e.g., HMAC-signed nonce) before completing the auth flow |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Hub shows "thinking..." with no timeout feedback | Amit assumes Klaus is broken; closes and reopens, creating a second turn | Show a 30-second "still working..." indicator; if no reply after 120s (matching `LLM_TIMEOUT_SECONDS`), show "something went wrong — message is queued" |
| Push notification arrives but tapping it opens Safari browser not the installed PWA | Tap-to-open goes to wrong context; chat history not shown | Set `"start_url"` and `"scope"` in `manifest.json` correctly; handle `notificationclick` in the service worker with `clients.openWindow(self.registration.scope)` |
| Habit check-off has no optimistic UI — the server round-trip feels slow | Tapping a habit feels laggy; user double-taps; two completions logged | Use optimistic UI: mark the habit checked immediately in local state, write to server in background, revert on error |
| Today timeline mixes meal slot times as "events" at 08:00/12:00/20:00 | Amit sees "Breakfast" at 08:00 even though he ate at 09:30 — confusing as a timeline event | Render meal slots as a section header ("Nutrition") in the timeline, not as timed events. Never show canonical slot times as actual eating times (CLAUDE.md invariant) |
| Telegram mirror sends Klaus's hub reply as a Telegram message during the transition period | Amit gets duplicate notifications — hub push + Telegram notification for every reply | Make the mirror flag per-message-type: mirror autonomous outreach (proactive) but not conversational replies from the hub |

---

## "Looks Done But Isn't" Checklist

- [ ] **iOS Push permission:** The "Enable Notifications" button is a real `<button onClick>` handler — verify there is no `async` call between the click event and `Notification.requestPermission()`.
- [ ] **iOS Push delivery:** After 5 test pushes on an installed iPhone PWA, push permission is still active (not revoked). Confirm by checking notification settings in iOS Settings → Klaus app.
- [ ] **SPA fallback:** `POST /webhook/telegram` returns `{"ok": true}` (JSON) not HTML after the catch-all route is added.
- [ ] **Cron OIDC auth:** After `SessionMiddleware` is added, all Cloud Scheduler cron endpoints still return 200 with valid OIDC tokens and 401 without.
- [ ] **Conversation `source` field:** Every message in Firestore has a `source` field (`"telegram"` or `"hub"`). Verified by checking a Firestore document directly.
- [ ] **`index.html` headers:** `curl -I https://<cloud-run-url>/` returns `Cache-Control: no-cache` on the first response and after a hard refresh on the installed iPhone PWA.
- [ ] **Workbox config:** `/api/*` URLs are NOT listed in the Workbox precache manifest and NOT matched by any `runtimeCaching` entry. Verified by inspecting the built `sw.js`.
- [ ] **Cloud Tasks for chat:** `/api/chat` never calls `background_tasks.add_task`. Verified by grep: `grep -r "BackgroundTasks" interfaces/` returns no hits in the chat handler.
- [ ] **Streak timezone:** `compute_streak` unit test includes a completion at 23:50 IST and verifies it counts for the correct IST date, not the UTC date.
- [ ] **TickTick import reconciliation:** Import script prints (or writes) a report of tasks with downgraded recurrence before Amit cancels the TickTick subscription.
- [ ] **Push subscription 410 handling:** When the Python push delivery function receives a 410, the subscription is deleted from `PushSubscriptionStore` within the same request, not left for a background cleanup.
- [ ] **Dual delivery routing:** Autonomous tick messages that reach `scheduled_message.py` are delivered via Web Push to the hub AND mirrored to Telegram only when the `TELEGRAM_MIRROR_ENABLED` flag is true — not unconditionally.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| SPA fallback shadows Telegram webhook (discover in prod) | HIGH | Immediately revert the catch-all route; re-register with correct ordering; test with synthetic Telegram update before re-enabling |
| Service worker cache poisoning after a deploy | MEDIUM | Serve `index.html` with `Cache-Control: no-cache, no-store`; force service worker update via a new SW version hash; instruct user to uninstall and reinstall the PWA on iPhone if still broken |
| iOS push subscription mass-revocation | MEDIUM | All affected subscriptions show as invalid in `PushSubscriptionStore`; display "re-enable notifications" prompt in the hub on next open; no data loss, but user action required |
| SessionMiddleware breaks all cron jobs | HIGH | Revert the middleware change; scope session middleware to `/api/*` sub-app before re-deploying; run full cron smoke test before next deploy |
| TickTick tasks lost in import (discovered after subscription cancelled) | HIGH | TickTick allows re-subscription for 30 days after cancellation for data export; re-export and re-import with corrected RRULE mapping; the reconciliation report would have prevented this |
| Streak counts corrupted by UTC timezone bug | LOW | Recompute all streaks server-side using corrected `Asia/Jerusalem` timezone function; one-time Firestore backfill job; no user data is lost |
| Hub chat BackgroundTask → 18-minute reply | MEDIUM | Mirror the fix from commit `80809f9`; move to Cloud Tasks dispatch; deploy; verify with a test message turn timing under 60s |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| iOS push permission user gesture | Phase 4 (Web Push) | Permission dialog appears after button tap on installed iPhone PWA |
| iOS push subscription revocation via missing `event.waitUntil()` | Phase 4 (Web Push) | After 10 test pushes, iOS push permission is still active |
| Push subscription 410 not cleaned up | Phase 4 (Web Push) | Simulate a 410 response in tests; verify subscription deleted from store |
| `index.html` cache poisoning | Phase 1 (Shell) | `Cache-Control: no-cache` confirmed on every `/` response |
| SPA fallback shadows webhook/cron routes | Phase 1 (Shell) | Telegram webhook smoke test passes after catch-all is registered |
| SessionMiddleware conflicts with OIDC cron auth | Phase 1 (Shell) | All cron endpoints return 200 with OIDC token after session middleware is added |
| Dual-interface double reply | Phase 1 (source field) + Phase 4 (mirror flag) | Send from hub; verify single reply in hub and single mirror in Telegram |
| Firestore polling cost blowup | Phase 1 (Shell) | `GET /api/messages?since=` query observed in Cloud Run logs (not full collection scan) |
| Cloud Run cold start serving stale API cache | Phase 1 (Shell) | No `/api/**` URLs in Workbox `runtimeCaching`; verified in built `sw.js` |
| Cloud Tasks invariant violated for hub chat | Phase 1 (Shell) | No `BackgroundTasks` usage in chat handler; Cloud Run request logs show `/internal/process-update` after `/api/chat` |
| TickTick RRULE / timezone import errors | Phase 2 (Tasks) | Reconciliation report reviewed before TickTick subscription cancelled |
| Habit streak timezone Asia/Jerusalem | Phase 3 (Habits) | Unit test: 23:50 IST completion counts for correct IST date |

---

## Sources

- Live codebase: `interfaces/web_server.py`, `core/task_dispatch.py`, `core/scheduled_message.py`, `memory/firestore_conversation.py`, `mcp_tools/ticktick_tool.py`, `CLAUDE.md` invariants
- Approved design spec: `docs/superpowers/specs/2026-06-13-klaus-hub-design.md`
- Known incident: slow-reply 2026-06-12 (commit `80809f9`) — BackgroundTask CPU throttle root cause
- iOS Web Push installed-PWA-only + user gesture requirement: [PWA Push Notifications on iOS in 2026](https://webscraft.org/blog/pwa-pushspovischennya-na-ios-u-2026-scho-realno-pratsyuye?lang=en), [OneSignal iOS Web Push](https://documentation.onesignal.com/docs/en/web-push-for-ios)
- iOS subscription revocation via missing `event.waitUntil()`: [How to fix iOS push subscriptions being terminated after 3 notifications](https://dev.to/progressier/how-to-fix-ios-push-subscriptions-being-terminated-after-3-notifications-39a7), [Apple Developer Forums — Web Push response always success](https://developer.apple.com/forums/thread/719990)
- VAPID 410 handling: [Web Push Error 410](https://blog.pushpad.xyz/2021/01/web-push-error-410-the-push-subscription-has-expired-or-the-user-has-unsubscribed/)
- Vite PWA / Workbox `index.html` no-cache: [Workbox GitHub issue #1528](https://github.com/GoogleChrome/workbox/issues/1528), [vite-plugin-pwa prompt-for-update guide](https://vite-pwa-org.netlify.app/guide/prompt-for-update)
- FastAPI SPA catch-all route ordering: [FastAPI Discussion #11502](https://github.com/fastapi/fastapi/discussions/11502), [Serving a React Frontend with FastAPI](https://davidmuraya.com/blog/serving-a-react-frontend-application-with-fastapi/)
- Cloud Run CPU throttle + background tasks: [Cloud Run CPU allocation blog](https://cloud.google.com/blog/topics/developers-practitioners/use-cloud-run-always-cpu-allocation-background-work), [Medium: How Cloud Run Default CPU Throttling Turned 18s Into 8 Minutes](https://medium.com/@buckwheat469/how-cloud-runs-default-cpu-throttling-turned-an-18-second-response-into-an-8-minute-timeout-63c3abc74df1)
- Firestore billing for polling: [Firestore real-time queries at scale](https://firebase.google.com/docs/firestore/real-time_queries_at_scale)

---
*Pitfalls research for: v5.0 Klaus Hub — adding PWA + Web Push + dual-interface chat to existing Klaus agent*
*Researched: 2026-06-13*
