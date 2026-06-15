---
phase: 26-hub-shell
verified: 2026-06-15T12:00:00Z
status: gaps_found
score: 11/17 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Today timeline shows all-day events pinned at top (TIME-01)"
    status: failed
    reason: >
      Backend `_today_calendar()` returns `all_day` as a list of dicts
      `{id, title, start, end}`, but `TodayData.calendar.all_day` is typed as
      `string[]` in `frontend/src/api/today.ts` and `TimelineDay.tsx` renders
      `calendar.all_day.map((title, i) => … {title} …)`. Rendering a plain JS
      object as a React child throws a runtime error ("Objects are not valid as a
      React child") when any all-day event is present. Frontend tests pass because
      they mock `all_day` with strings.
    artifacts:
      - path: "interfaces/web_server.py"
        issue: "_today_calendar returns all_day as list of dicts, not strings"
      - path: "frontend/src/api/today.ts"
        issue: "TodayData.calendar.all_day typed as string[] — does not match backend"
      - path: "frontend/src/components/timeline/TimelineDay.tsx"
        issue: "all_day.map((title, i) => {title}) expects strings, receives objects"
    missing:
      - "Change all_day type in api/today.ts to AllDayEvent[] with id/title/start/end"
      - "Update TimelineDay.tsx all_day render to use ev.title instead of the item itself"
      - "Fix backend to return the dict structure the frontend needs, or align frontend to backend"

  - truth: "Timeline header shows Garmin morning stats (sleep, HRV, body battery) — TIME-02"
    status: failed
    reason: >
      Backend `_today_garmin()` returns keys `sleep_hours`, `hrv_overnight`,
      `body_battery_morning` but the frontend `GarminStats` interface declares
      `sleep`, `hrv`, `body_battery`. `GarminStatsRows` reads `garmin.sleep`,
      `garmin.hrv`, `garmin.body_battery` — all undefined from the real backend
      response. Only `resting_hr` matches. Sleep, HRV and body battery rows
      silently disappear (the `value !== null ? <p>` guard hides them).
      Frontend tests mock the garmin dict with `{sleep, hrv, body_battery, resting_hr}`
      which matches the type but not the actual backend.
    artifacts:
      - path: "interfaces/web_server.py"
        issue: "_today_garmin returns sleep_hours / hrv_overnight / body_battery_morning"
      - path: "frontend/src/api/today.ts"
        issue: "GarminStats interface: { sleep, hrv, body_battery, resting_hr } — mismatched names"
      - path: "frontend/src/components/timeline/TimelineHeader.tsx"
        issue: "GarminStatsRows reads garmin.sleep / garmin.hrv / garmin.body_battery (all undefined)"
    missing:
      - "Align field names: either rename backend keys to sleep/hrv/body_battery, or update GarminStats interface and component to match sleep_hours/hrv_overnight/body_battery_morning"

  - truth: "Training item shows block context 'Week N of 16 — Lower Body A' (TIME-04)"
    status: partial
    reason: >
      Backend `_today_training()` returns a dict with key `block_label` (not `item`).
      Frontend `TrainingItem` interface has `item: string` and `TrainingRow` renders
      `{training.item}` for the item title — always undefined. The `block_context`
      field name matches and renders correctly, but the training item's title/label
      is blank. Tests use mock data with `{item: 'Lower Body A'}` that matches the
      frontend type but not the backend output.
    artifacts:
      - path: "interfaces/web_server.py"
        issue: "_today_training returns block_label not item"
      - path: "frontend/src/api/today.ts"
        issue: "TrainingItem interface has item: string — backend sends block_label"
      - path: "frontend/src/components/timeline/TimelineItem.tsx"
        issue: "TrainingRow renders {training.item} which is always undefined"
    missing:
      - "Either rename backend field to `item` or add `item` alias, OR rename TrainingItem.item to block_label in frontend type + component"

  - truth: "Located events show leave-by / Get Ready chips (TIME-05)"
    status: failed
    reason: >
      Backend `_today_routes()` attaches `leave_by_minutes_before` (integer minutes)
      and `routes_summary` to located events. Frontend `TimedEvent` expects `leave_by`
      and `get_ready_at` as ISO datetime strings. The EventItem component checks
      `event.leave_by` and `event.get_ready_at` (always undefined from the actual
      backend) so the chips never render. The frontend has no logic to convert
      `leave_by_minutes_before` into a leave-by datetime. `get_ready_at` (Get Ready
      time accounting for 45min pre-departure) is not computed by the backend at all.
    artifacts:
      - path: "interfaces/web_server.py"
        issue: "_today_routes attaches leave_by_minutes_before (int) not leave_by (ISO str)"
      - path: "frontend/src/api/today.ts"
        issue: "TimedEvent.leave_by is string | undefined; backend sends leave_by_minutes_before integer"
      - path: "frontend/src/components/timeline/TimelineItem.tsx"
        issue: "EventItem checks event.leave_by and event.get_ready_at — both always undefined"
    missing:
      - "Backend: compute ISO leave_by datetime from event.start - leave_by_minutes_before and expose as leave_by; compute get_ready_at = leave_by - 45min (Amit's Get Ready time per USER.md)"
      - "OR frontend: derive leave_by from event.start and leave_by_minutes_before client-side and display minutes label"

  - truth: "Glance rail shows the day's nutrition running totals (TIME-08, desktop)"
    status: failed
    reason: >
      `GlanceRail.tsx` renders a hardcoded "No meals logged yet today." placeholder.
      The `nutrition_totals` data from `/api/today` flows into `TimelineDay` and is
      passed to `TimelineHeader` (phone strip) but never reaches `GlanceRail`.
      There is no prop-pass, context, or query from `GlanceRail` to the today data.
      Desktop users always see the static placeholder regardless of what they ate.
      The phone nutrition strip (via TimelineHeader) works correctly.
    artifacts:
      - path: "frontend/src/components/layout/GlanceRail.tsx"
        issue: "Hardcoded placeholder text; no data connection to /api/today or useToday"
      - path: "frontend/src/components/timeline/TimelineDay.tsx"
        issue: "nutrition_totals only forwarded to TimelineHeader (phone), not to GlanceRail"
    missing:
      - "Wire nutrition_totals to GlanceRail: either via React context (NutritionContext), shared zustand slice, or by making GlanceRail call useToday() directly"
      - "Update GlanceRail to render real kcal/protein/carbs/fat from the data"

human_verification:
  - test: "iOS PWA install: open hub in Safari on iPhone, confirm install banner appears, tap 'How to install', dismiss and re-open — confirm it stays dismissed"
    expected: "Banner shows on first visit to an iOS device not in standalone mode; dismissed state persists via localStorage"
    why_human: "navigator.standalone and display-mode: standalone only work on a real iOS device in Safari; cannot test in jsdom or CI"

  - test: "Hub-Telegram shared conversation: send a message from the hub chat and verify it appears in Telegram; send from Telegram and verify it appears in hub on next poll"
    expected: "Both surfaces show identical message history, keyed on the same telegram_user_id in FirestoreConversationStore"
    why_human: "Requires a live Cloud Run deployment with Telegram bot, Cloud Tasks queue, and Firestore — end-to-end integration test"

  - test: "Live traffic-aware leave-by (TIME-05): add a calendar event with a real address (once leave_by field mismatch is fixed), confirm the chip shows the correct estimated departure time"
    expected: "Routes API returns travel minutes; backend computes ISO leave_by; chip renders 'Leave by HH:MM'"
    why_human: "Requires live Google Routes API call from Cloud Run; blocked until the leave_by field mismatch gap is closed"

  - test: "PWA home-screen icon: install Klaus from Safari on an iPhone, check that the home-screen icon shows the correct apple-touch-icon (not a generic Safari icon)"
    expected: "Icon matches /apple-touch-icon.png as declared in index.html"
    why_human: "On-device icon rendering only verifiable on a physical iOS device"

  - test: "Responsive layout on phone: navigate Today/Klaus/Habits/Health tabs, confirm BottomTabs are visible and Sidebar is hidden; on desktop confirm Sidebar visible and BottomTabs hidden"
    expected: "md: breakpoint correctly splits layouts via Tailwind md:hidden / hidden md:flex classes"
    why_human: "CSS breakpoint behavior requires a real viewport; jsdom does not implement media queries"
---

# Phase 26: Hub Shell — Verification Report

**Phase Goal:** Amit can open the Klaus Hub on phone or desktop, sign in with Google, see today's full timeline (calendar, meals, training plan, Garmin stats, weather, leave-by times, coach note), and exchange chat messages with Klaus — all reflected in the Telegram conversation history.

**Verified:** 2026-06-15T12:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | HUB-01: Google Sign-In issues itsdangerous-signed httpOnly session cookie allowlisted to Amit's account | VERIFIED | `interfaces/hub_auth.py`: `verify_google_id_token` + `create_session_cookie` with HMAC-SHA256 TimestampSigner, 365-day max_age, httpOnly=True, samesite="strict". `tests/test_hub_auth.py` flipped from skips to real assertions. |
| 2 | HUB-01: `/api/*` routes return 401 without valid session cookie | VERIFIED | `require_hub_session` FastAPI Depends() applied to `/api/today`, `/api/chat`, `/api/chat/messages`. `CRON_DEV_BYPASS` bypass for local dev. |
| 3 | HUB-02: App installs as PWA on iOS with in-app Add-to-Home-Screen banner | VERIFIED (code) / HUMAN | `InstallBanner.tsx` + `useInstallBanner.ts` implement D-12 gate (iOS && !standalone && !dismissed). `index.html` carries apple-touch-icon. `vite.config.ts` declares PWA manifest with standalone display. On-device behavior requires human test. |
| 4 | HUB-03: Service worker uses network-first for index.html, cache-first for hashed assets | VERIFIED | `vite.config.ts` VitePWA with generateSW, NetworkFirst on `request.destination === 'document'`, CacheFirst on `/assets/.+(js\|css)`. |
| 5 | HUB-03: Shell loads with skeletons on bad connection; offline indicator appears | VERIFIED | `OfflineIndicator.tsx` + `useOnline.ts` render amber top strip when offline. `TimelineDay.tsx` shows SkeletonBlock during isLoading. `Skeleton.tsx` shared component available for all future consumers. |
| 6 | HUB-04: SPA mount is the absolute last route; existing routes are not shadowed | VERIFIED | `SPAStaticFiles` mounted via `app.mount("/", ...)` at the end of `web_server.py` (line 1680). All API/cron/internal/trigger routes registered before it. Guard: `os.path.isdir(_DIST_PATH)` prevents startup failure without a build. |
| 7 | HUB-05: One responsive app — desktop sidebar + timeline + glance rail + collapsible dock; phone bottom tabs with Klaus center | VERIFIED (code) / HUMAN | `AppShell.tsx` renders all layout components; `md:hidden` / `hidden md:flex` classes split phone/desktop. `DockChat` collapses to 48px via chevron. `BottomTabs` has Klaus as center tab with UnreadBadge. Responsive behavior needs human test in real viewport. |
| 8 | CHAT-01: Hub messages use the SAME FirestoreConversationStore as Telegram, keyed on telegram_user_id | VERIFIED | `/api/chat` POST: `store.append(user_id, "user", content)` and `/internal/process-hub-message` append with the same `FirestoreConversationStore` keyed on `telegram_user_id` from `_resolve_hub_user_id()`. End-to-end round-trip needs human test. |
| 9 | CHAT-02: Hub messages dispatched via Cloud Tasks full-CPU path (`/internal/process-hub-message`) | VERIFIED | `enqueue_hub_message()` in `core/task_dispatch.py` targets `/internal/process-hub-message` via Cloud Tasks. Route is OIDC-gated via `_verify_cron_request`. `POST /api/chat` calls `enqueue_hub_message`, never a `BackgroundTask`. |
| 10 | CHAT-03: Optimistic send with sending/sent/error states; 2.5s polling with "Klaus is thinking…" indicator | VERIFIED | `useChat.ts`: `useMutation` with `onMutate` optimistic append (`status:'sending'`), `onError` rollback, `onSettled` invalidate. `refetchInterval: isVisible ? 2500 : false`. `TypingIndicator.tsx` renders "Klaus is thinking…" when last message is role='user'. |
| 11 | CHAT-04: Unread badge counting messages received since last-seen, cleared on scroll-to-bottom | VERIFIED | `useUnread.ts` uses `localStorage.last_seen_seq`. Badge computed as `max(0, messageCount - lastSeen)`. `ChatWindow.tsx` calls `markAllSeen()` via IntersectionObserver on last message. `BottomTabs.tsx` and `DockChat.tsx` both show `UnreadBadge`. |
| 12 | TIME-01: Calendar shows all-day events pinned at top, timed events chronologically | FAILED | Backend `_today_calendar` returns `all_day` as list of dicts `{id, title, start, end}`. Frontend types it as `string[]` and renders `{title}` (the full dict object). React will throw "Objects are not valid as a React child" on any day with all-day events. |
| 13 | TIME-02: Header shows Garmin morning stats + one-line weather | FAILED (Garmin) / VERIFIED (weather) | Backend `_today_garmin` returns `sleep_hours`/`hrv_overnight`/`body_battery_morning`; frontend `GarminStats` reads `sleep`/`hrv`/`body_battery`. Three of four Garmin fields are always undefined → rows hidden. Weather string assembled correctly and passed through. |
| 14 | TIME-03: Meals shown as slot labels with macros, never eating-time framing | VERIFIED | Backend emits `slot_label`/`slot_time`/`macros` with no `eaten_at` or `eating_time` field. `MealRow` in `TimelineItem.tsx` renders `slot_label` ("Breakfast"/"Lunch"/"Dinner") and macro grid. CLAUDE.md §6 invariant enforced at both layers. |
| 15 | TIME-04: Training item with block context "Week N of 16" | FAILED (title) / PARTIAL (context) | Backend returns `block_label` not `item`. `TrainingItem` type has `item: string`; `TrainingRow` renders `{training.item}` → always undefined (blank). `block_context` field name matches and would render "Week N of 16 — …" correctly. |
| 16 | TIME-05: Located events show leave-by / Get Ready chips | FAILED | Backend attaches `leave_by_minutes_before` (int) + `routes_summary`. Frontend `TimedEvent` expects `leave_by?: string` (ISO) and `get_ready_at?: string` (ISO). Chips check `event.leave_by` and `event.get_ready_at` — both always undefined. `get_ready_at` computation is absent from backend. |
| 17 | TIME-07: Timeline shows morning coach note from morning briefing | VERIFIED | Backend `_today_coach_note` reads `SelfStateStore.daily_note` guarded by `daily_note_date == today_iso`. `core/morning_briefing.py` writes `daily_note` + `daily_note_date` after compose. `TimelineDay.tsx` renders the note or "Coach note coming after your morning briefing." D-06 placeholder. |
| 18 | TIME-08: Glance rail shows nutrition running totals | FAILED (desktop) / VERIFIED (phone) | `GlanceRail.tsx` renders hardcoded placeholder "No meals logged yet today." — `nutrition_totals` is never passed to it. Phone header strip (`TimelineHeader`) receives and renders `nutrition_totals` correctly via `NutritionStrip`. Desktop glance rail is disconnected. |

**Score:** 11/17 must-haves verified (12 counting TIME-08 phone as partial)

### Gaps Summary

5 gaps block the phase goal. The common root cause is a backend↔frontend field-name contract that was established independently in plans 26-04 (backend) and 26-07 (frontend) without a shared schema contract. The frontend unit tests (mocked) match the frontend type but not the actual backend, so all 1410 Python + 51 vitest tests pass despite the integration being broken.

**Gap 1 (TIME-01 — all-day events):** Backend returns objects; frontend types strings. Severity: runtime crash on days with all-day events.

**Gap 2 (TIME-02 — Garmin):** Three-of-four field name mismatches. Sleep/HRV/body battery all invisible. Severity: silent data loss.

**Gap 3 (TIME-04 — Training title):** `block_label` vs `item`. Training item title is blank. Severity: partial rendering (block_context shows correctly).

**Gap 4 (TIME-05 — Leave-by chips):** Backend emits minutes integer + summary string; frontend expects ISO datetime strings. Leave-by/Get Ready chips never appear. `get_ready_at` not computed anywhere. Severity: feature absent.

**Gap 5 (TIME-08 — Desktop glance rail):** `GlanceRail.tsx` is wired to no data source. Desktop nutrition totals always show static placeholder. Severity: feature absent on desktop.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `interfaces/hub_auth.py` | GIS verify + signed session cookie + require_hub_session + revocation | VERIFIED | Full implementation: verify_google_id_token, create_session_cookie, verify_session_cookie, get_session_version, require_hub_session. All security controls (T-26-03-01..08) implemented. |
| `interfaces/web_server.py` | /api/auth/google, /api/auth/logout, /api/auth/revoke-all, /api/today, /api/chat, /api/chat/messages, /internal/process-hub-message, SPAStaticFiles last | VERIFIED | All 8 hub routes registered before SPA mount. SPAStaticFiles at line 1680. |
| `core/task_dispatch.py` | enqueue_hub_message → /internal/process-hub-message | VERIFIED | `enqueue_hub_message(content, user_id)` targets `/internal/process-hub-message` with same OIDC pattern as `enqueue_update`. |
| `memory/firestore_db.py` | session_version + telegram_user_id in UserProfileStore._SCAFFOLD | VERIFIED | Lines 217-218: `session_version: 0`, `telegram_user_id: None` in _SCAFFOLD. |
| `frontend/vite.config.ts` | VitePWA generateSW, NetworkFirst document, CacheFirst assets | VERIFIED | Contains VitePWA plugin with correct handler strategies. |
| `frontend/index.html` | apple-touch-icon link | VERIFIED | Line 6: `<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />` |
| `Dockerfile` | Multi-stage Node build → Python runtime, COPY --from=frontend-builder | VERIFIED | Stage 1: `frontend-builder` node:20-slim runs `npm ci && npm run build`. Stage 2: `COPY --from=frontend-builder /frontend/dist ./frontend/dist`. |
| `frontend/src/components/layout/AppShell.tsx` | Responsive root layout | VERIFIED | `flex flex-col md:flex-row`. All layout components mounted: Sidebar, BottomTabs, GlanceRail, DockChat, OfflineIndicator, InstallBanner. |
| `frontend/src/api/client.ts` | fetch wrapper with credentials:'include' + 401 redirect | VERIFIED | `credentials: 'include'` on every call. 401 → `window.location.href = '/?signin=required'`. |
| `frontend/src/hooks/useChat.ts` | optimistic send + 2.5s polling | VERIFIED | `refetchInterval: isVisible ? 2500 : false`. `useMutation` with `onMutate` optimistic append, `onError` rollback. |
| `frontend/src/hooks/useUnread.ts` | localStorage last_seen_seq + unread badge | VERIFIED | `last_seen_seq` key in localStorage, `unreadCount = max(0, messageCount - lastSeen)`. |
| `frontend/src/components/chat/TypingIndicator.tsx` | "Klaus is thinking…" indicator | VERIFIED | Exact text "Klaus is thinking…" per Copywriting Contract. 3-dot bounce animation. |
| `frontend/src/components/shared/InstallBanner.tsx` | iOS install banner, dismissible | VERIFIED | Gate via `useInstallBanner` (isIOS && !isStandalone && !dismissed). Dismiss persists to localStorage. |
| `frontend/src/components/shared/OfflineIndicator.tsx` | Amber offline strip | VERIFIED | Renders amber (#F59E0B) top strip with "Offline — showing cached data" when `!isOnline`. |
| `frontend/src/components/shared/Skeleton.tsx` | Shared shimmer component | VERIFIED | `animate-pulse` on `#1F1F1F`, role="status". |
| `frontend/src/api/today.ts` | Today API types + fetchToday | PARTIAL | Types exist but `all_day: string[]` should be object array; `GarminStats` field names mismatch backend; `TrainingItem.item` mismatches `block_label`. |
| `frontend/src/components/layout/GlanceRail.tsx` | Nutrition running totals display | FAILED | Hardcoded placeholder. No data connection. |

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `web_server.py` | `hub_auth.py` | `Depends(require_hub_session)` on /api/* | VERIFIED | Lines 1351, 1480, 1548: `_email: str = Depends(require_hub_session)` on /api/today, /api/chat, /api/chat/messages |
| `hub_auth.py` | `firestore_db.py` | `UserProfileStore.session_version` read | VERIFIED | `get_session_version()` imports `UserProfileStore` and reads `session_version` |
| `web_server.py` | `task_dispatch.py` | POST /api/chat → enqueue_hub_message | VERIFIED | Line 1535: `ok = await loop.run_in_executor(None, enqueue_hub_message, content, user_id)` |
| `web_server.py` | `firestore_conversation.py` | shared FirestoreConversationStore keyed on telegram_user_id | VERIFIED | Lines 1524-1529 and 1632-1637 both use `FirestoreConversationStore` with the same `user_id` from `_resolve_hub_user_id()` |
| `App.tsx` | `SignInPage.tsx` | route guard redirects unauthenticated | VERIFIED | `if (isError || !data?.email) { return <SignInPage /> }` |
| `api/client.ts` | `/api/auth/me` | session check on load | VERIFIED | `apiFetch` used by `fetchMe` in `api/auth.ts`; `credentials: 'include'` on all calls |
| `useChat.ts` | `/api/chat` + `/api/chat/messages` | useMutation POST + useQuery poll | VERIFIED | `postChatMessage` (mutation) + `fetchMessages` (query with refetchInterval) |
| `TimelineDay.tsx` | `useToday.ts` | renders composed timeline data | VERIFIED | `const { data, isLoading, isError, error } = useToday()` |
| `useToday.ts` | `/api/today` | apiFetch in TanStack useQuery | VERIFIED | `queryFn: fetchToday` → `apiFetch<TodayData>('/api/today')` |
| `TimelineDay.tsx` → `GlanceRail.tsx` | `nutrition_totals` | context/prop pass | NOT_WIRED | nutrition_totals only passed to TimelineHeader (phone); GlanceRail has no data source |
| Backend training dict | Frontend TrainingItem | `block_label` → `item` field | NOT_WIRED | Backend sends `block_label`; frontend reads `item` — data never displays |
| Backend garmin dict | Frontend GarminStats | field name alignment | NOT_WIRED | Backend sends `sleep_hours`/`hrv_overnight`/`body_battery_morning`; frontend reads `sleep`/`hrv`/`body_battery` |
| Backend routes dict | Frontend TimedEvent leave_by | `leave_by_minutes_before` → `leave_by` ISO string | NOT_WIRED | Backend sends minutes integer; frontend expects ISO string |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `TimelineDay.tsx` | `data.calendar.all_day` | `/api/today` → `_today_calendar` | Yes, but wrong type (objects not strings) | HOLLOW — type mismatch causes render failure |
| `TimelineDay.tsx` | `data.garmin` | `/api/today` → `_today_garmin` | Yes, but 3/4 field names wrong | HOLLOW — sleep/hrv/body_battery always undefined |
| `TimelineDay.tsx` | `data.training.item` | `/api/today` → `_today_training` | No — backend sends block_label | HOLLOW — training title always undefined |
| `TimelineDay.tsx` → `TimelineHeader.tsx` | `nutritionTotals` | `/api/today` → `_today_nutrition_totals` | Yes | FLOWING (phone strip only) |
| `GlanceRail.tsx` | nutrition data | none | No | DISCONNECTED — hardcoded placeholder |
| `TimelineItem.tsx` (event) | `event.leave_by` | `/api/today` → `_today_routes` | No — backend sends `leave_by_minutes_before` integer | HOLLOW — leave_by always undefined |
| `useChat.ts` | `messages` | `/api/chat/messages` → `FirestoreConversationStore` | Yes | FLOWING |
| `ChatWindow.tsx` | `isKlausThinking` | derived from messages | Yes | FLOWING |

## Behavioral Spot-Checks

Step 7b skipped for frontend UI components (no runnable entry points without a live server). Backend routes verified via test coverage only.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Python suite green | `pytest tests/ -q` (reported) | 1410 passed | PASS |
| Frontend build + vitest | `npm run build && npm test` (reported) | Build clean, 51 vitest pass | PASS (mocked data hides API contract mismatches) |
| `/api/today` auth gate | Test: `test_hub_auth.py` coverage | 401 without cookie | PASS |
| `/internal/process-hub-message` OIDC gate | `_verify_cron_request` applied | OIDC verified | PASS |

## Requirements Coverage

| Requirement | Phase Plan | Status | Evidence |
|-------------|-----------|--------|----------|
| HUB-01 | 26-03 | SATISFIED | hub_auth.py + /api/auth/* routes + require_hub_session Depends() |
| HUB-02 | 26-01, 26-09 | SATISFIED (code) | InstallBanner.tsx + useInstallBanner.ts + apple-touch-icon in index.html + PWA manifest |
| HUB-03 | 26-01, 26-09 | SATISFIED | NetworkFirst index.html + CacheFirst assets in vite.config.ts + OfflineIndicator + Skeleton |
| HUB-04 | 26-01 | SATISFIED | SPAStaticFiles mounted last; all existing routes untouched |
| HUB-05 | 26-06 | SATISFIED (code) | AppShell responsive layout; BottomTabs phone + Sidebar/GlanceRail/DockChat desktop |
| CHAT-01 | 26-05 | SATISFIED (code) | Shared FirestoreConversationStore via telegram_user_id; live round-trip needs human test |
| CHAT-02 | 26-05 | SATISFIED | enqueue_hub_message + /internal/process-hub-message; no BackgroundTask |
| CHAT-03 | 26-08 | SATISFIED | useChat optimistic send + 2.5s polling + TypingIndicator |
| CHAT-04 | 26-08 | SATISFIED | useUnread localStorage badge + IntersectionObserver markAllSeen |
| TIME-01 | 26-04, 26-07 | BLOCKED | all_day type mismatch (objects vs strings) — runtime crash on days with all-day events |
| TIME-02 | 26-04, 26-07 | BLOCKED | Garmin field names mismatched (sleep_hours vs sleep, hrv_overnight vs hrv, body_battery_morning vs body_battery) |
| TIME-03 | 26-04, 26-07 | SATISFIED | Slot labels + macros only; no eaten_at/eating_time; invariant enforced at backend + frontend |
| TIME-04 | 26-04, 26-07 | BLOCKED | Training title field mismatch (block_label vs item) — title always blank |
| TIME-05 | 26-04, 26-07 | BLOCKED | leave_by_minutes_before (int) vs leave_by (ISO string); get_ready_at not computed |
| TIME-07 | 26-02, 26-04, 26-07 | SATISFIED | SelfStateStore.daily_note written by morning briefing; date-guarded in _today_coach_note |
| TIME-08 | 26-04, 26-07 | BLOCKED (desktop) | GlanceRail not wired to nutrition_totals; phone strip works |

**Orphaned requirements check:** TIME-06 (Habits/supplements) is mapped to Phase 28 per REQUIREMENTS.md — not orphaned. All Phase 26 requirements (HUB-01..05, CHAT-01..04, TIME-01..05, TIME-07, TIME-08) are covered by one of the 9 plans.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/layout/GlanceRail.tsx` | 69 | Hardcoded placeholder "No meals logged yet today." with no data fetch | BLOCKER | Desktop nutrition totals never display (TIME-08) |
| `frontend/src/api/today.ts` | 85 | `all_day: string[]` type mismatch vs backend object array | BLOCKER | Runtime crash when all-day events present (TIME-01) |
| `frontend/src/api/today.ts` | 63-68 | `GarminStats { sleep, hrv, body_battery }` mismatched vs backend `sleep_hours, hrv_overnight, body_battery_morning` | BLOCKER | 3/4 Garmin fields always undefined (TIME-02) |
| `frontend/src/api/today.ts` | 77 | `TrainingItem.item` vs backend `block_label` | BLOCKER | Training title always blank (TIME-04) |
| `frontend/src/api/today.ts` | 35-36 | `TimedEvent.leave_by`/`get_ready_at` (ISO string) vs backend `leave_by_minutes_before` (int) | BLOCKER | Leave-by chips never render (TIME-05) |
| `frontend/src/components/timeline/TimelineDay.tsx` | 28 | Local SkeletonBlock stub ("replaced by shared Skeleton from 26-09") — 26-09 shipped but TimelineDay still uses the local stub | WARNING | Skeleton shimmer exists (animates) but is not the shared canonical Skeleton |
| `frontend/src/components/timeline/TimelineHeader.tsx` | 28 | Local SkeletonLine stub — same as above | WARNING | Minor: stub works but canonical Skeleton.tsx not adopted here |

**No TBD/FIXME/XXX debt markers found** in files modified by this phase.

## Human Verification Required

### 1. iOS PWA Install Flow

**Test:** Open the hub URL in Safari on an iPhone (not in standalone mode, first visit). Confirm the "Add Klaus to your home screen" banner appears. Tap "How to install", follow instructions, add to home screen. Re-open and confirm the banner is gone.
**Expected:** Banner shows on first iOS visit; expanded instructions appear on CTA tap; banner stays dismissed after close.
**Why human:** `navigator.standalone` and `display-mode: standalone` only work on a physical iOS device; `useInstallBanner` gate cannot be verified in jsdom or CI.

### 2. Hub-Telegram Shared Conversation Round-Trip

**Test:** On a live Cloud Run deployment, send a message from the hub chat UI. Check Telegram — confirm the message appears. Send a reply from Telegram. Poll the hub chat — confirm the reply appears.
**Expected:** Both surfaces share the same `FirestoreConversationStore` history; hub polling (2.5s) surfaces the Telegram reply with "Klaus is thinking…" while the Cloud Tasks turn completes.
**Why human:** Requires a deployed Cloud Run with Telegram bot, Cloud Tasks queue, and live Firestore; no integration test covers the full round-trip.

### 3. Responsive Layout on Real Devices

**Test:** On a phone (< 768px viewport), confirm only BottomTabs are visible (no Sidebar, no DockChat). On desktop, confirm Sidebar + GlanceRail + DockChat visible and BottomTabs hidden. Collapse DockChat with the chevron.
**Expected:** Tailwind `md:hidden` / `hidden md:flex` classes split layouts correctly; DockChat transitions smoothly to 48px.
**Why human:** jsdom does not implement media queries; Tailwind breakpoints only fire in a real browser viewport.

### 4. PWA Home Screen Icon (iOS)

**Test:** After installing from Safari, check the iPhone home screen — confirm the Klaus icon appears correctly (not a generic Safari screenshot).
**Expected:** `/apple-touch-icon.png` as declared in `index.html` line 6.
**Why human:** iOS home screen icon rendering only verifiable on a physical device.

### 5. Leave-by Chips with Live Routes API (after gap closure)

**Test:** Once the leave_by field mismatch is fixed, add a calendar event with a real street address in Tel Aviv. Open the hub hub on the day of the event, confirm a "Leave by HH:MM" chip appears with a traffic-aware time.
**Expected:** Routes API returns drive time; backend computes ISO leave_by = event.start - duration; chip renders with formatted time.
**Why human:** Requires live Google Routes API call from a deployed Cloud Run; cannot be faked in unit tests.

---

_Verified: 2026-06-15T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
