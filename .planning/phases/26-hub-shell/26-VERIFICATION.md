---
phase: 26-hub-shell
verified: 2026-06-17T10:30:00Z
status: verified
status_note: "17/17 automated truths verified; human UAT closed against the live deploy (rev klaus-agent-00120-lrj) — core hub verified working on iPhone + desktop. Cosmetic/UX items (chat scroll, leave-by chips live-check, icon art, error-boundary hardening) deferred to a dedicated fixes session — see 26-HUMAN-UAT.md."
score: 17/17 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 11/17
  gaps_closed:
    - "TIME-01: all_day now returns string[] from backend (title strings, not dicts)"
    - "TIME-02: _today_garmin now returns {sleep, hrv, body_battery, resting_hr} matching GarminStats"
    - "TIME-04: _today_training now returns item field (split_name or block label), matching TrainingItem.item"
    - "TIME-05: _today_routes now computes ISO leave_by and get_ready_at; leave_by_minutes_before removed"
    - "TIME-08: GlanceRail now calls useToday() and renders data.nutrition_totals — no longer a hardcoded placeholder"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "iOS PWA install: open hub in Safari on iPhone, confirm install banner appears, tap 'How to install', dismiss and re-open — confirm it stays dismissed"
    expected: "Banner shows on first visit to an iOS device not in standalone mode; dismissed state persists via localStorage"
    why_human: "navigator.standalone and display-mode: standalone only work on a real iOS device in Safari; cannot test in jsdom or CI"

  - test: "Hub-Telegram shared conversation: send a message from the hub chat and verify it appears in Telegram; send from Telegram and verify it appears in hub on next poll"
    expected: "Both surfaces show identical message history, keyed on the same telegram_user_id in FirestoreConversationStore"
    why_human: "Requires a live Cloud Run deployment with Telegram bot, Cloud Tasks queue, and Firestore — end-to-end integration test"

  - test: "Responsive layout on phone: navigate Today/Klaus/Habits/Health tabs, confirm BottomTabs are visible and Sidebar is hidden; on desktop confirm Sidebar visible and BottomTabs hidden"
    expected: "md: breakpoint correctly splits layouts via Tailwind md:hidden / hidden md:flex classes"
    why_human: "CSS breakpoint behavior requires a real viewport; jsdom does not implement media queries"

  - test: "PWA home-screen icon: install Klaus from Safari on an iPhone, check that the home-screen icon shows the correct apple-touch-icon (not a generic Safari icon)"
    expected: "Icon matches /apple-touch-icon.png as declared in index.html"
    why_human: "On-device icon rendering only verifiable on a physical iOS device"

  - test: "Live traffic-aware leave-by (TIME-05): add a calendar event with a real address in Tel Aviv, confirm the chip shows the correct estimated departure time"
    expected: "Routes API returns travel minutes; backend computes ISO leave_by = event.start − duration; get_ready_at = leave_by − 45 min; chips render 'Leave by HH:MM' / 'Get Ready at HH:MM'"
    why_human: "Requires live Google Routes API call from a deployed Cloud Run; unit test mocks routes_tool"
---

# Phase 26: Hub Shell — Verification Report (Re-verification)

**Phase Goal:** Amit can open the Klaus Hub on phone or desktop, sign in with Google, see today's full timeline (calendar, meals, training plan, Garmin stats, weather, leave-by times, coach note), and exchange chat messages with Klaus — all reflected in the Telegram conversation history.

**Verified:** 2026-06-15T14:00:00Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure (commit c004f0e closes all 5 BLOCKERs from initial verification)

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | HUB-01: Google Sign-In issues itsdangerous-signed httpOnly session cookie allowlisted to Amit's account | VERIFIED | `interfaces/hub_auth.py`: `verify_google_id_token` + `create_session_cookie` with HMAC-SHA256 TimestampSigner, 365-day max_age, httpOnly=True, samesite="strict". |
| 2 | HUB-01: `/api/*` routes return 401 without valid session cookie | VERIFIED | `require_hub_session` FastAPI Depends() applied to `/api/today`, `/api/chat`, `/api/chat/messages`. `test_unauthenticated_returns_401` in `tests/test_api_today.py` confirms. |
| 3 | HUB-02: App installs as PWA on iOS with in-app Add-to-Home-Screen banner | VERIFIED (code) / HUMAN | `InstallBanner.tsx` + `useInstallBanner.ts` implement D-12 gate (iOS && !standalone && !dismissed). `index.html` carries apple-touch-icon. `vite.config.ts` declares PWA manifest. On-device behavior requires human test. |
| 4 | HUB-03: Service worker uses network-first for index.html, cache-first for hashed assets | VERIFIED | `vite.config.ts` VitePWA with generateSW, NetworkFirst on `request.destination === 'document'`, CacheFirst on `/assets/.+(js\|css)`. |
| 5 | HUB-03: Shell loads with skeletons on bad connection; offline indicator appears | VERIFIED | `OfflineIndicator.tsx` + `useOnline.ts` render amber top strip when offline. `TimelineDay.tsx` shows SkeletonBlock during isLoading. |
| 6 | HUB-04: SPA mount is the absolute last route; existing routes are not shadowed | VERIFIED | `SPAStaticFiles` mounted via `app.mount("/", ...)` at the end of `web_server.py` (line 1680). All API/cron/internal/trigger routes registered before it. |
| 7 | HUB-05: One responsive app — desktop sidebar + timeline + glance rail + collapsible dock; phone bottom tabs | VERIFIED (code) / HUMAN | `AppShell.tsx` renders all layout components; `md:hidden` / `hidden md:flex` classes split phone/desktop. `DockChat` collapses via chevron. `BottomTabs` has Klaus as center tab. Responsive behavior needs human test in real viewport. |
| 8 | CHAT-01: Hub messages use the SAME FirestoreConversationStore as Telegram | VERIFIED | `/api/chat` POST and `/internal/process-hub-message` both use `FirestoreConversationStore` keyed on `_resolve_hub_user_id()`. End-to-end round-trip needs human test. |
| 9 | CHAT-02: Hub messages dispatched via Cloud Tasks full-CPU path | VERIFIED | `enqueue_hub_message()` in `core/task_dispatch.py` targets `/internal/process-hub-message`. Never a `BackgroundTask`. |
| 10 | CHAT-03: Optimistic send + 2.5s polling + "Klaus is thinking…" indicator | VERIFIED | `useChat.ts`: `useMutation` with `onMutate` optimistic append, `onError` rollback, `refetchInterval: isVisible ? 2500 : false`. `TypingIndicator.tsx` renders "Klaus is thinking…". |
| 11 | CHAT-04: Unread badge counting messages received since last-seen, cleared on scroll | VERIFIED | `useUnread.ts` uses `localStorage.last_seen_seq`. Badge = `max(0, messageCount - lastSeen)`. `ChatWindow.tsx` calls `markAllSeen()` via IntersectionObserver. |
| 12 | TIME-01: Calendar shows all-day events pinned at top (string titles), timed events chronologically | VERIFIED | `_today_calendar` appends `entry["title"]` (a string) to `all_day` for date-only events. Backend `all_day: string[]` matches frontend `TodayData.calendar.all_day: string[]`. `TimelineDay.tsx` renders `calendar.all_day.map((title, i) => … {title} …)` — strings, no React child crash. |
| 13 | TIME-02: Header shows Garmin morning stats (sleep, HRV, body battery, resting_hr) and weather | VERIFIED | `_today_garmin` returns `{"sleep": data.get("sleep_hours"), "hrv": data.get("hrv_overnight"), "body_battery": data.get("body_battery_morning"), "resting_hr": data.get("resting_hr")}`. Keys match `GarminStats` interface and `GarminStatsRows` reads `garmin.sleep`/`garmin.hrv`/`garmin.body_battery`/`garmin.resting_hr`. `test_today_garmin_maps_to_frontend_contract` asserts exact output shape. |
| 14 | TIME-03: Meals shown as slot labels with macros; no eating-time inference | VERIFIED | Backend emits `slot_label`/`slot_time`/`macros`. `MealRow` renders `slot_label`. No `eaten_at` or `eating_time` fields. `test_meal_slot_time_not_eating_time` enforces this. |
| 15 | TIME-04: Training item with block context "Week N of 16 — Lower Body A" | VERIFIED | `_today_training` returns `"item": split_name or block.get("label")` — the `item` key now exists and maps to the workout name. `TrainingRow` renders `{training.item}` (now populated) and `Chip label={training.block_context}`. `test_today_returns_expected_keys` asserts `"item" in data["training"]`. |
| 16 | TIME-05: Located events show ISO leave_by / get_ready_at chips | VERIFIED | `_today_routes` computes `leave_by_dt = start_dt - timedelta(minutes=duration_minutes)` and `get_ready_at = leave_by_dt - timedelta(minutes=45)`, stores as ISO strings. Old `leave_by_minutes_before` field is gone. `EventItem` renders `event.leave_by` and `event.get_ready_at` chips. `test_today_routes_computes_iso_leave_by_and_get_ready` asserts correct datetime math and absence of old field. Live Routes API call needs human test. |
| 17 | TIME-08: Glance rail shows nutrition running totals on desktop | VERIFIED | `GlanceRail.tsx` imports `useToday`, reads `data?.nutrition_totals`, and renders kcal/protein/carbs/fat/fiber rows when `totals.kcal > 0`. Hardcoded placeholder is now the empty-state fallback (no meals logged), not the always-shown state. Phone nutrition strip in `TimelineHeader` was already verified in initial pass. |

**Score:** 17/17 truths verified (5 previously failed, all now VERIFIED; 12 previously verified, all regression-clear)

---

## Re-verification: Gap Closure Evidence

### Gap 1 — TIME-01 (all_day type mismatch) — CLOSED

**What was wrong:** `_today_calendar` returned `all_day` as list of dicts `{id, title, start, end}`. Frontend typed and rendered it as `string[]`, causing "Objects are not valid as a React child" crash.

**Fix verified:** `web_server.py` line 1062: `all_day.append(entry["title"])`. The `entry` dict is built but only the title string is appended to `all_day`. `TimelineDay.tsx` `all_day.map((title, i) => … {title} …)` now receives strings. `today.ts` `all_day: string[]` type matches exactly.

### Gap 2 — TIME-02 (Garmin field name mismatch) — CLOSED

**What was wrong:** Backend returned `sleep_hours`/`hrv_overnight`/`body_battery_morning`; frontend `GarminStats` declared `sleep`/`hrv`/`body_battery`.

**Fix verified:** `web_server.py` lines 1084–1089: `_today_garmin` now explicitly remaps source keys → `{"sleep": data.get("sleep_hours"), "hrv": data.get("hrv_overnight"), "body_battery": data.get("body_battery_morning"), "resting_hr": data.get("resting_hr")}`. All four keys match `GarminStats`. `test_today_garmin_maps_to_frontend_contract` passes a realistic `fetch_garmin_today` mock with old-style keys and asserts output is `{"sleep": 7.5, "hrv": 55, "body_battery": 78, "resting_hr": 52}`.

### Gap 3 — TIME-04 (block_label vs item) — CLOSED

**What was wrong:** `_today_training` returned `block_label` but frontend `TrainingItem` type declared `item: string`. `TrainingRow` rendered `{training.item}` → always undefined.

**Fix verified:** `web_server.py` line 1230: `"item": split_name or block.get("label")`. The `item` key is now present and contains the workout title (split name or block label). `block_label` is still returned as an additional field but `item` satisfies the frontend contract. `test_today_returns_expected_keys` asserts `"item" in data["training"]`.

### Gap 4 — TIME-05 (leave_by_minutes_before vs ISO strings) — CLOSED

**What was wrong:** Backend set `leave_by_minutes_before` (integer). Frontend expected `leave_by: string` and `get_ready_at: string` (ISO datetimes). `get_ready_at` was not computed at all.

**Fix verified:** `web_server.py` lines 1284–1297: `_attach_leave_by` inner function computes `leave_by_dt = start_dt - timedelta(minutes=duration_minutes)` and `ev["get_ready_at"] = (leave_by_dt - timedelta(minutes=45)).isoformat()`. Both are set as ISO strings. No `leave_by_minutes_before` field exists anywhere (`grep` returns empty). `test_today_routes_computes_iso_leave_by_and_get_ready` verifies the datetime arithmetic and explicitly asserts `"leave_by_minutes_before" not in ev`.

### Gap 5 — TIME-08 (GlanceRail hardcoded placeholder) — CLOSED

**What was wrong:** `GlanceRail.tsx` always rendered "No meals logged yet today." with no data source.

**Fix verified:** `GlanceRail.tsx` now imports `useToday`, calls `const { data } = useToday()`, extracts `data?.nutrition_totals`, and conditionally renders five `NutritionRow` components when `totals.kcal > 0`. The "No meals logged yet today." string is now the `hasData === false` branch — a correct empty-state, not a hardcoded stub. React Query deduplicates the `['today']` query key so no second network request is made.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `interfaces/hub_auth.py` | GIS verify + signed session cookie + require_hub_session | VERIFIED | Full implementation unchanged from initial pass. |
| `interfaces/web_server.py` | All hub routes + _today_* helpers with correct field names | VERIFIED | All 5 contract-drift fixes applied. `_today_garmin` remaps keys; `_today_calendar` appends strings; `_today_training` returns `item`; `_today_routes` sets ISO `leave_by`/`get_ready_at`; no `leave_by_minutes_before` anywhere. |
| `core/task_dispatch.py` | enqueue_hub_message | VERIFIED | Unchanged and verified. |
| `memory/firestore_db.py` | session_version + telegram_user_id scaffold | VERIFIED | Unchanged and verified. |
| `frontend/vite.config.ts` | VitePWA generateSW, NetworkFirst/CacheFirst | VERIFIED | Unchanged and verified. |
| `frontend/index.html` | apple-touch-icon | VERIFIED | Unchanged and verified. |
| `Dockerfile` | Multi-stage Node build | VERIFIED | Unchanged and verified. |
| `frontend/src/components/layout/AppShell.tsx` | Responsive root layout | VERIFIED | Unchanged and verified. |
| `frontend/src/api/today.ts` | Today API types matching backend | VERIFIED | `all_day: string[]`, `GarminStats {sleep, hrv, body_battery, resting_hr}`, `TrainingItem {item, block_context}`, `TimedEvent {leave_by?, get_ready_at?}` — all now match backend. |
| `frontend/src/api/client.ts` | fetch wrapper with credentials + 401 redirect | VERIFIED | Unchanged and verified. |
| `frontend/src/components/layout/GlanceRail.tsx` | Nutrition running totals from useToday | VERIFIED | Calls `useToday()`, reads `data?.nutrition_totals`, renders 5 NutritionRow items when `kcal > 0`. |
| `frontend/src/components/timeline/TimelineDay.tsx` | Today timeline orchestrator | VERIFIED | Renders `all_day.map((title, i) => … {title} …)` with strings. |
| `frontend/src/components/timeline/TimelineItem.tsx` | TrainingRow renders training.item | VERIFIED | `TrainingRow` renders `{training.item}` — now populated by backend. Leave-by/get_ready_at chips read ISO strings. |
| `frontend/src/components/timeline/TimelineHeader.tsx` | GarminStatsRows reads correct field names | VERIFIED | Reads `garmin.sleep`/`garmin.hrv`/`garmin.body_battery`/`garmin.resting_hr` — now matches backend output. |
| `frontend/src/hooks/useChat.ts` | Optimistic send + 2.5s polling | VERIFIED | Unchanged and verified. |
| `frontend/src/hooks/useUnread.ts` | localStorage badge | VERIFIED | Unchanged and verified. |
| `frontend/src/components/chat/TypingIndicator.tsx` | "Klaus is thinking…" | VERIFIED | Unchanged and verified. |
| `frontend/src/components/shared/InstallBanner.tsx` | iOS install banner | VERIFIED | Unchanged and verified. |
| `frontend/src/components/shared/OfflineIndicator.tsx` | Amber offline strip | VERIFIED | Unchanged and verified. |
| `tests/test_api_today.py` | Contract tests locking field names | VERIFIED | `test_today_garmin_maps_to_frontend_contract` patches `fetch_garmin_today` and asserts exact `{sleep, hrv, body_battery, resting_hr}` output. `test_today_routes_computes_iso_leave_by_and_get_ready` asserts ISO datetimes and absence of `leave_by_minutes_before`. `test_today_returns_expected_keys` asserts `"item" in data["training"]` and `set(data["garmin"]) >= {"sleep", "hrv", "body_battery", "resting_hr"}`. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `web_server.py` | `hub_auth.py` | `Depends(require_hub_session)` on /api/* | VERIFIED | Unchanged. |
| `hub_auth.py` | `firestore_db.py` | `UserProfileStore.session_version` | VERIFIED | Unchanged. |
| `web_server.py` | `task_dispatch.py` | POST /api/chat → enqueue_hub_message | VERIFIED | Unchanged. |
| `web_server.py` | `firestore_conversation.py` | Shared store keyed on telegram_user_id | VERIFIED | Unchanged. |
| `App.tsx` | `SignInPage.tsx` | Route guard on isError/no email | VERIFIED | Unchanged. |
| `useChat.ts` | `/api/chat` + `/api/chat/messages` | useMutation + useQuery | VERIFIED | Unchanged. |
| `TimelineDay.tsx` | `useToday.ts` | `useToday()` hook | VERIFIED | Unchanged. |
| `useToday.ts` | `/api/today` | `apiFetch` in TanStack useQuery | VERIFIED | Unchanged. |
| `GlanceRail.tsx` | `nutrition_totals` | `useToday()` direct call | VERIFIED | Now wired: `const { data } = useToday(); const totals = data?.nutrition_totals`. React Query deduplicates the ['today'] query — no extra fetch. |
| Backend `_today_training` | Frontend `TrainingItem.item` | `"item": split_name or block.get("label")` | VERIFIED | Field `item` now present in backend response; `TrainingRow` renders it. |
| Backend `_today_garmin` | Frontend `GarminStats` | Key remapping in `_today_garmin` | VERIFIED | `sleep_hours` → `sleep`, `hrv_overnight` → `hrv`, `body_battery_morning` → `body_battery`. |
| Backend `_today_routes` | Frontend `TimedEvent.leave_by`/`get_ready_at` | `_attach_leave_by` sets ISO strings | VERIFIED | ISO strings computed and attached; old `leave_by_minutes_before` integer removed. |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `TimelineDay.tsx` | `calendar.all_day` | `_today_calendar` → `all_day.append(entry["title"])` | Yes — string[] | FLOWING |
| `TimelineHeader.tsx` | `garmin.sleep/hrv/body_battery/resting_hr` | `_today_garmin` → explicit key remap | Yes — all 4 keys present | FLOWING |
| `TimelineItem.tsx` (TrainingRow) | `training.item` | `_today_training` → `"item": split_name or block.get("label")` | Yes — populated string | FLOWING |
| `TimelineItem.tsx` (EventItem) | `event.leave_by`, `event.get_ready_at` | `_today_routes` → `_attach_leave_by` ISO strings | Yes for located events | FLOWING (live Routes API: human test) |
| `GlanceRail.tsx` | `totals` (nutrition_totals) | `useToday()` → `data?.nutrition_totals` | Yes — same query cache as TimelineDay | FLOWING |
| `TimelineDay.tsx` → `TimelineHeader.tsx` | `nutritionTotals` | `useToday()` → `data.nutrition_totals` prop | Yes | FLOWING |
| `useChat.ts` | `messages` | `/api/chat/messages` → `FirestoreConversationStore` | Yes | FLOWING |

---

## Behavioral Spot-Checks

Step 7b skipped for frontend UI components (no runnable entry points without a live server). Backend contract verified via test suite.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Python suite green (1412 passed) | `pytest tests/ -q` (reported) | 1412 passed, 3 skipped, 0 failed | PASS |
| Frontend build clean | `npm run build` (reported) | Clean build | PASS |
| Frontend vitest (51 pass) | `npm test` (reported) | 51 vitest pass | PASS |
| Garmin contract test | `test_today_garmin_maps_to_frontend_contract` | asserts `{"sleep", "hrv", "body_battery", "resting_hr"}` | PASS |
| Routes ISO contract test | `test_today_routes_computes_iso_leave_by_and_get_ready` | asserts ISO strings + absence of `leave_by_minutes_before` | PASS |
| Nested key assertions | `test_today_returns_expected_keys` | asserts `garmin >= {sleep, hrv, body_battery, resting_hr}` + `"item" in training` | PASS |
| 401 without session | `test_unauthenticated_returns_401` | 401 confirmed | PASS |

---

## Requirements Coverage

| Requirement | Phase Plan | Status | Evidence |
|-------------|-----------|--------|----------|
| HUB-01 | 26-03 | SATISFIED | hub_auth.py + /api/auth/* routes + require_hub_session Depends() |
| HUB-02 | 26-01, 26-09 | SATISFIED (code) | InstallBanner.tsx + useInstallBanner.ts + apple-touch-icon + PWA manifest |
| HUB-03 | 26-01, 26-09 | SATISFIED | NetworkFirst index.html + CacheFirst assets + OfflineIndicator + Skeleton |
| HUB-04 | 26-01 | SATISFIED | SPAStaticFiles mounted last; all existing routes untouched |
| HUB-05 | 26-06 | SATISFIED (code) | AppShell responsive layout; BottomTabs phone + Sidebar/GlanceRail/DockChat desktop |
| CHAT-01 | 26-05 | SATISFIED (code) | Shared FirestoreConversationStore via telegram_user_id; live round-trip needs human test |
| CHAT-02 | 26-05 | SATISFIED | enqueue_hub_message + /internal/process-hub-message; no BackgroundTask |
| CHAT-03 | 26-08 | SATISFIED | useChat optimistic send + 2.5s polling + TypingIndicator |
| CHAT-04 | 26-08 | SATISFIED | useUnread localStorage badge + IntersectionObserver markAllSeen |
| TIME-01 | 26-04, 26-07 | SATISFIED | all_day now string[] from backend; TimelineDay.tsx map renders title strings — no React child crash |
| TIME-02 | 26-04, 26-07 | SATISFIED | Garmin keys remapped to {sleep, hrv, body_battery, resting_hr}; all 4 rows visible |
| TIME-03 | 26-04, 26-07 | SATISFIED | Slot labels + macros only; no eaten_at/eating_time; invariant enforced at both layers |
| TIME-04 | 26-04, 26-07 | SATISFIED | `item` field returned by backend; TrainingRow renders it + block_context chip |
| TIME-05 | 26-04, 26-07 | SATISFIED (code) | ISO leave_by + get_ready_at computed and attached; chips render from ISO strings; live Routes API test is human-only |
| TIME-07 | 26-02, 26-04, 26-07 | SATISFIED | SelfStateStore.daily_note written by morning briefing; date-guarded in _today_coach_note |
| TIME-08 | 26-04, 26-07 | SATISFIED | GlanceRail calls useToday(); renders nutrition_totals when kcal > 0; phone strip also flowing |

**Orphaned requirements check:** TIME-06 (Habits/supplements) maps to Phase 28 per REQUIREMENTS.md — not orphaned. All 16 Phase 26 requirements covered.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/timeline/TimelineDay.tsx` | 52–64 | Local `SkeletonBlock` stub — comment says "replaced by shared Skeleton from 26-09" but 26-09 has shipped | WARNING | Skeleton shimmer works (animate-pulse) but canonical `Skeleton.tsx` not adopted; cosmetic only |
| `frontend/src/components/timeline/TimelineHeader.tsx` | 28–41 | Local `SkeletonLine` stub — same as above | WARNING | Minor: stub is functionally equivalent; canonical Skeleton.tsx exists but not imported here |

**No TBD/FIXME/XXX debt markers** found in files modified by this phase.

**Stub classification note:** The `GlanceRail.tsx` "No meals logged yet today." string is NOT a stub in the re-verified code — it is the legitimate empty-state branch (`hasData === false`). It was a stub in the initial verification because it was unconditionally rendered; now it is gated on `!totals || totals.kcal === 0`.

---

## Human Verification Required

### 1. iOS PWA Install Flow

**Test:** Open the hub URL in Safari on an iPhone (not in standalone mode, first visit). Confirm the "Add Klaus to your home screen" banner appears. Tap "How to install", follow instructions, add to home screen. Re-open and confirm the banner is gone.
**Expected:** Banner shows on first iOS visit; expanded instructions appear on CTA tap; banner stays dismissed after close.
**Why human:** `navigator.standalone` and `display-mode: standalone` only work on a physical iOS device; `useInstallBanner` gate cannot be verified in jsdom or CI.

### 2. Hub-Telegram Shared Conversation Round-Trip

**Test:** On a live Cloud Run deployment, send a message from the hub chat UI. Check Telegram — confirm the message appears. Send a reply from Telegram. Poll the hub chat — confirm the reply appears within 2–3 seconds.
**Expected:** Both surfaces share the same `FirestoreConversationStore` history; hub polling (2.5s) surfaces the Telegram reply with "Klaus is thinking…" while the Cloud Tasks turn completes.
**Why human:** Requires a deployed Cloud Run with Telegram bot, Cloud Tasks queue, and live Firestore; no integration test covers the full round-trip.

### 3. Responsive Layout on Real Devices

**Test:** On a phone (< 768px viewport), confirm only BottomTabs are visible (no Sidebar, no DockChat). On desktop, confirm Sidebar + GlanceRail + DockChat visible and BottomTabs hidden. Collapse DockChat with the chevron.
**Expected:** Tailwind `md:hidden` / `hidden md:flex` classes split layouts correctly; DockChat transitions smoothly to 48px.
**Why human:** jsdom does not implement media queries; Tailwind breakpoints only fire in a real browser viewport.

### 4. PWA Home Screen Icon (iOS)

**Test:** After installing from Safari, check the iPhone home screen — confirm the Klaus icon appears correctly (not a generic Safari screenshot).
**Expected:** `/apple-touch-icon.png` as declared in `index.html`.
**Why human:** iOS home screen icon rendering only verifiable on a physical device.

### 5. Leave-by Chips with Live Routes API (TIME-05)

**Test:** Add a calendar event with a real street address in Tel Aviv. Open the hub on the day of the event. Confirm a "Leave by HH:MM" chip and a "Get Ready at HH:MM" chip appear with traffic-aware times.
**Expected:** Routes API returns drive time; backend computes `leave_by = event.start − duration` and `get_ready_at = leave_by − 45 min`; both chips render with correctly formatted times.
**Why human:** Requires live Google Routes API call from a deployed Cloud Run; unit test mocks `get_travel_time`.

---

_Verified: 2026-06-15T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
