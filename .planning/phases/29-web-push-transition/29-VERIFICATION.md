---
phase: 29-web-push-transition
verified: 2026-07-05T00:00:00Z
status: passed
score: 37/38 must-haves verified (code); 2 items require physical-device / mirror-week human verification (not gaps)
overrides_applied: 0
requirements_coverage:
  - id: PUSH-01
    status: satisfied
  - id: PUSH-02
    status: satisfied
  - id: PUSH-03
    status: satisfied
  - id: PUSH-04
    status: satisfied
human_verification:
  - test: "D-20 #1 Enable-push flow on physical iPhone"
    expected: "Tapping enable from Settings or the Today banner triggers the iOS permission prompt (user gesture); permission granted; a subscription document appears in Firestore push_subscriptions (confirmable via get_push_health)."
    why_human: "Requires a real iOS Safari/PWA permission prompt and physical device gesture — cannot be exercised in a headless test environment."
  - test: "D-20 #2 Chat-reply push with app fully closed"
    expected: "With the installed PWA swiped away, a Telegram-turn reply or hub-originated reply arrives as a lock-screen push notification."
    why_human: "iOS APNs delivery to a closed app cannot be observed from source code or CI; requires a physical device witness."
  - test: "D-20 #3 Proactive push with app fully closed"
    expected: "An autonomous-tick outreach or a manually-triggered cron (briefing/nightly review) arrives as a push notification while the app is fully closed."
    why_human: "Same as above — real APNs delivery must be witnessed on-device."
  - test: "D-20 #4 Icon unread badge"
    expected: "After a closed-app push, the installed home-screen icon shows an unread-count badge; opening the app and viewing chat clears both the in-app counter and the icon badge."
    why_human: "The iOS/PWA Badging API render on the home-screen icon is not observable outside a physical device."
  - test: "D-21 One-week Telegram-mirror observation"
    expected: "telegram_mirror_enabled stays true for >=7 days of real production use with every Telegram message matched by a push (daily double-buzz audit, zero unexplained misses) before Amit flips the mirror off."
    why_human: "This is a calendar-time production observation, not a code-verifiable property; tracked in 29-HUMAN-UAT.md Section 2 and intentionally kept open past this phase's code-complete point (D-21)."
---

# Phase 29: Web Push & Transition Verification Report

**Phase Goal:** Amit receives Klaus's replies and proactive messages as native push notifications on the installed iPhone PWA when the app is closed, Telegram continues to mirror all messages during a transition period, and the installed icon shows an unread-count badge.
**Verified:** 2026-07-05
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria — the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Amit can enable push notifications from a button (user gesture) inside the installed PWA; subscription stored in `PushSubscriptionStore` and re-validated on each hub open | ✓ VERIFIED (code) | `frontend/src/hooks/usePush.ts::enablePush` calls `pushManager.subscribe` from a real `onClick` in `SettingsPage.tsx`/`PushEnableBanner.tsx`; POSTs to `/api/push/subscribe`; `interfaces/web_server.py::api_push_subscribe` validates (`https://` + p256dh/auth) and upserts via `PushSubscriptionStore.upsert`; `usePush.revalidate` re-checks on mount + `visibilitychange`→visible |
| 2 | Klaus's replies and proactive autonomous-tick messages are delivered as push notifications when the app is closed, wrapped in `event.waitUntil`, verified on a physical device | ✓ VERIFIED (code) / pending device witness | `frontend/src/sw.ts` push listener always calls `showNotification` inside `event.waitUntil`; all three send paths (`interfaces/_router.py` Telegram-turn, `interfaces/web_server.py` hub reply, `core/scheduled_message.send_and_inject` proactive crons) call `send_push_to_all` via `run_in_executor`. Physical-device confirmation is D-20, tracked pending in `29-HUMAN-UAT.md` — see Human Verification section |
| 3 | Proactive messages mirror to Telegram behind a flag left ON for >=1 week before disabling; mirror path validated in production before retirement | ✓ VERIFIED (code) / pending 1-week observation | `HubSettingsStore` defaults `telegram_mirror_enabled=True`; `send_and_inject` mirrors to Telegram whenever the flag is true, at full volume (no `disable_notification` anywhere in the codebase — grep confirmed); `toggle_telegram_mirror` brain tool implements the D-11 conversational retirement path. The >=1-week production observation is D-21, tracked pending in `29-HUMAN-UAT.md` Section 2 |
| 4 | The installed PWA icon shows an unread-count badge via the Badging API (not a favicon library) | ✓ VERIFIED (code) | `frontend/src/hooks/useAppBadge.ts` calls `navigator.setAppBadge`/`clearAppBadge`, wired into `ChatWindow.tsx` with the real `unreadCount` from `useUnread`; `sw.ts` push handler independently increments an IndexedDB counter and calls `setAppBadge` while the app is closed |

**Score (roadmap SCs):** 4/4 code-complete; SC #2 and #3 additionally require a physical-device witness (D-20) and a calendar-week production observation (D-21) respectively before the phase can be considered fully closed — both are explicitly out-of-band per this phase's design (10-plan roadmap ends on D-20 UAT) and are routed to Human Verification below, not gaps.

### Plan-Level Must-Haves (granular, from PLAN frontmatter — 10 plans)

| # | Plan | Truth | Status |
|---|------|-------|--------|
| 1 | 29-01 | `pywebpush` importable in project venv | ✓ VERIFIED — `.venv/bin/python -c "import pywebpush"` succeeds |
| 2 | 29-01 | VAPID private key retrievable from Secret Manager `klaus-vapid-private-key` | ✓ VERIFIED — `core/push_sender.py::_get_vapid_private_key` calls `access_secret_version`; runbook in `docs/DEPLOYMENT.md` §27 documents secret creation |
| 3 | 29-01 | `VAPID_PUBLIC_KEY` documented as required env var | ✓ VERIFIED — present in `.env.example` and `docs/DEPLOYMENT.md` |
| 4 | 29-02 | workbox-precaching/routing/strategies/expiration/core direct devDeps at ^7.4.1 | ✓ VERIFIED — `frontend/package.json` |
| 5 | 29-02 | `29-HUMAN-UAT.md` exists with D-20 checklist + D-21 tracking | ✓ VERIFIED — file present, both sections populated |
| 6 | 29-03 | Push subscription CRUD (upsert idempotent, list, delete, success/failure), multi-subscription | ✓ VERIFIED — `PushSubscriptionStore` in `memory/firestore_db.py:3466`; `tests/test_push_subscription_store.py` passing |
| 7 | 29-03 | Telegram-mirror flag + `push_enabled_at` in one hub-settings doc, default ON | ✓ VERIFIED — `HubSettingsStore` in `memory/firestore_db.py:3576`; `tests/test_hub_settings_store.py` passing |
| 8 | 29-03 | Every read feeding `json.dumps` passed through `_jsonsafe_doc` | ✓ VERIFIED — `/api/settings` GET/PATCH and `get_push_health` both call `_jsonsafe_doc` |
| 9 | 29-04 | Single sync fan-out function with per-class TTL (D-07) | ✓ VERIFIED — `core/push_sender.py::send_push_to_all`, `CLASS_TTL` dict with 7 classes |
| 10 | 29-04 | Payload title "Klaus" + body = text (capped [:1000], documented D-12 deviation), one notification per message | ✓ VERIFIED — `push_sender.py:119-129`, no `tag` set |
| 11 | 29-04 | 404/410 deletes dead subscription; other errors stamp `failure_count`; success stamps `last_success_at` | ✓ VERIFIED — `push_sender.py:151-167`; WR-03 fix confirmed live (delivery accounting isolated from bookkeeping failures) |
| 12 | 29-04 | VAPID key cached; fresh `vapid_claims` per send; `timeout=10` on every `webpush()` call | ✓ VERIFIED |
| 13 | 29-05 | `toggle_telegram_mirror` brain-direct tool | ✓ VERIFIED — `core/tools.py:788`, dispatched via `_HANDLERS["toggle_telegram_mirror"]` |
| 14 | 29-05 | `get_push_health` brain-direct tool | ✓ VERIFIED — `core/tools.py:809`, dispatched via `_HANDLERS["get_push_health"]` |
| 15 | 29-05 | Heartbeat `_check_push_health` registered, severity downgraded while mirror ON | ✓ VERIFIED — `core/heartbeat.py:248-318`, registered in signal collection at line 720 |
| 16 | 29-06 | Frontend fetches VAPID public key over session-authed endpoint | ✓ VERIFIED — `GET /api/push/vapid-public-key` behind `require_hub_session` |
| 17 | 29-06 | Frontend registers subscription; server validates + upserts | ✓ VERIFIED — `POST /api/push/subscribe` validates https+keys, then `run_in_executor` upsert |
| 18 | 29-06 | Frontend reads/PATCHes hub settings (mirror flag) | ✓ VERIFIED — `GET`/`PATCH /api/settings`, PATCH whitelists only `telegram_mirror_enabled` |
| 19 | 29-06 | First successful subscribe stamps `push_enabled_at` (D-14) | ✓ VERIFIED — `api_push_subscribe` stamps only when unset |
| 20 | 29-06 | All new routes require hub session; none touch OIDC cron/internal/trigger auth | ✓ VERIFIED — all four routes carry `Depends(require_hub_session)` |
| 21 | 29-07 | Custom SW (injectManifest) precaches + NetworkFirst(5s) index.html + CacheFirst assets + `SKIP_WAITING` | ✓ VERIFIED — `frontend/src/sw.ts`; `npm run build` confirms `mode injectManifest`, `dist/sw.js` generated |
| 22 | 29-07 | Push event always shows a notification inside `event.waitUntil` | ✓ VERIFIED — `sw.ts:159-186`, badge failure isolated in its own try/catch so it never suppresses `showNotification` |
| 23 | 29-07 | Push handler increments IndexedDB badge + `setAppBadge`; `notificationclick` always opens Today, no tag replacement | ✓ VERIFIED — `sw.ts:172-183` (no `tag` field), `notificationclick` posts `NAVIGATE path:'/'` |
| 24 | 29-08 | Every proactive send fans a push (unless chat visible) and mirrors to Telegram while flag ON, full volume | ✓ VERIFIED — `send_and_inject`; grep confirms `disable_notification` never used |
| 25 | 29-08 | No server-side quiet hours, no daily cap | ✓ VERIFIED — no such gating found in `push_sender.py`/`scheduled_message.py` |
| 26 | 29-08 | Push-send failures logged and swallowed, never raised | ✓ VERIFIED — `send_and_inject:168-176` wraps the push call in try/except with `logger.warning` |
| 27 | 29-08 | Interactive Telegram flows (check-in keyboards) push as plain text; Telegram keeps buttons while mirror is on | ✓ VERIFIED (mirror ON) — `core/training_checkin.py` passes `reply_markup=kb` through `send_and_inject`; **note:** WR-04 (undeliverable once mirror is off) is a documented, deliberately-deferred finding — see Deferred section |
| 28 | 29-08 | Hub chat replies and Telegram-turn replies also push | ✓ VERIFIED — `web_server.py:1746` and `_router.py:374` both call the push path with `message_class="chat_reply"` |
| 29 | 29-08 | Push skipped only when chat view reported visible within last few seconds (server D-02 gate) | ✓ VERIFIED — `scheduled_message.is_chat_visible()` / `mark_chat_visible()` |
| 30 | 29-08 | Chat poll carries `chat_visible=1` while chat view is visible (client D-02) | ✓ VERIFIED — `frontend/src/api/chat.ts`, `useChat.ts` |
| 31 | 29-08 | Push fan-out never blocks the event loop | ✓ VERIFIED — CR-01 fix confirmed live: `HubSettingsStore.get()` and conversation-inject both run via `loop.run_in_executor` |
| 32 | 29-09 | User gesture subscribes (fetch VAPID key → `pushManager.subscribe` → POST) | ✓ VERIFIED — `usePush.ts::enablePush` |
| 33 | 29-09 | On hub open, granted-but-missing subscription silently re-subscribes; only revoked permission surfaces re-enable banner (D-19) | ✓ VERIFIED — `usePush.ts::revalidate` |
| 34 | 29-09 | Icon badge reconciles to true unread count on open and clears at zero | ✓ VERIFIED — `useAppBadge.ts` |
| 35 | 29-10 | Amit can open Settings, enable push from a button, toggle Telegram mirror | ✓ VERIFIED — `SettingsPage.tsx` |
| 36 | 29-10 | First-run dismissible banner on Today prompts push enable (gesture-driven) | ✓ VERIFIED — `PushEnableBanner.tsx` rendered in App.tsx's `TodayPage` |
| 37 | 29-10 | Notification tap opens Today; viewing chat clears both tab badge and icon badge | ✓ VERIFIED — SW `NAVIGATE` bridge in `App.tsx`; `ChatWindow.tsx::useAppBadge(unreadCount)` + `markAllSeen` |
| 38 | 29-10 | Push arrives on the physical iPhone with app closed, icon badge appears (D-20) | ? HUMAN VERIFICATION REQUIRED — pending in `29-HUMAN-UAT.md` Section 1 (0/4 checks witnessed) |

**Score:** 37/38 plan-level must-haves verified from code + passing tests. Item 38 (and the roadmap SC #3 mirror-week observation) require physical-device / calendar-time verification that cannot be performed from the codebase — routed to Human Verification, not counted as a gap.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/push_sender.py` | `send_push_to_all` sync fan-out, VAPID load, CLASS_TTL, WR-03 best-effort reconciliation | ✓ VERIFIED | 170 lines, substantive, imported by `scheduled_message.py`, `interfaces/_router.py` |
| `memory/firestore_db.py::PushSubscriptionStore` | CRUD + failure-path methods | ✓ VERIFIED | class at line 3466; `upsert/list_all/delete/record_success/record_failure` all present |
| `memory/firestore_db.py::HubSettingsStore` | mirror flag + `push_enabled_at`, default ON | ✓ VERIFIED | class at line 3576 |
| `core/scheduled_message.py` | `send_and_inject` push+mirror+visibility gate, CR-01 fix | ✓ VERIFIED | lazy `_get_hub_settings_store()` singleton; blocking reads off-loaded via `run_in_executor` |
| `interfaces/web_server.py` | `/api/push/subscribe`, `/api/push/vapid-public-key`, `/api/settings` GET+PATCH | ✓ VERIFIED | all behind `require_hub_session`; PATCH whitelists one field |
| `interfaces/_router.py` | push after Telegram-turn `reply_text` | ✓ VERIFIED | `send_push_to_all` call at line 374 |
| `core/tools.py` | `toggle_telegram_mirror` + `get_push_health` | ✓ VERIFIED | registered in tool schema list and `_HANDLERS` dispatch |
| `core/heartbeat.py` | `_check_push_health` checker | ✓ VERIFIED | registered in `_collect_signals` |
| `frontend/src/sw.ts` | custom injectManifest SW: precache + runtime cache + SKIP_WAITING + push + notificationclick + WR-06 navigateFallback | ✓ VERIFIED | 204 lines, all handlers present |
| `frontend/vite.config.ts` | `injectManifest` strategy → `src/sw.ts` | ✓ VERIFIED | confirmed by `npm run build` output ("mode injectManifest") |
| `frontend/src/hooks/usePush.ts` | subscribe gesture + revalidate | ✓ VERIFIED | 194 lines, substantive |
| `frontend/src/hooks/useAppBadge.ts` | badge reconciliation | ✓ VERIFIED | 44 lines, wired into `ChatWindow.tsx` with real `unreadCount` |
| `frontend/src/components/settings/SettingsPage.tsx` | enable-push button + mirror toggle | ✓ VERIFIED | 195 lines, substantive |
| `frontend/src/components/shared/PushEnableBanner.tsx` | first-run banner | ✓ VERIFIED | 190 lines, rendered in `App.tsx` |
| `.planning/phases/29-web-push-transition/29-HUMAN-UAT.md` | D-20 + D-21 tracking doc | ✓ VERIFIED | present, status: pending (expected — device UAT not yet run) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `core/push_sender.py` | Secret Manager `klaus-vapid-private-key` | `access_secret_version` | ✓ WIRED | `_get_vapid_private_key()` |
| `core/push_sender.py` | `pywebpush.webpush` | encrypted VAPID send | ✓ WIRED | `send_push_to_all` |
| `core/scheduled_message.py` | `core/push_sender.send_push_to_all` | `run_in_executor` push fan-out | ✓ WIRED | line 171 |
| `core/scheduled_message.py` | `HubSettingsStore.get` | mirror gate, off-loaded | ✓ WIRED | CR-01 fix — `_load_hub_settings` via executor |
| `interfaces/web_server.py` | `PushSubscriptionStore.upsert` | `POST /api/push/subscribe` via executor | ✓ WIRED | line 2666 |
| `interfaces/web_server.py` | `HubSettingsStore` | `GET/PATCH /api/settings` | ✓ WIRED | lines 2715, 2742+ |
| `interfaces/_router.py` | `core/push_sender.send_push_to_all` | Telegram-turn reply push | ✓ WIRED | line 374, `message_class="chat_reply"` |
| `core/tools.py` | `HubSettingsStore.set` | `toggle_telegram_mirror` handler | ✓ WIRED | `_handle_toggle_telegram_mirror` |
| `core/heartbeat.py` | `PushSubscriptionStore.list_all` | `_check_push_health` | ✓ WIRED | line 267 |
| `frontend/src/sw.ts` | `workbox-precaching` | `precacheAndRoute` import | ✓ WIRED | confirmed by build output (13 precache entries) |
| `frontend/src/hooks/usePush.ts` | `/api/push/subscribe` | POST after subscribe | ✓ WIRED | `postSubscription` |
| `frontend/src/hooks/useAppBadge.ts` | `navigator.setAppBadge` | reconcile on `unreadCount` change | ✓ WIRED | and wired into `ChatWindow.tsx` with real data |
| `frontend/src/App.tsx` | `/settings` route + NAVIGATE bridge | route element + SW message listener | ✓ WIRED | line 193 route, lines 162-174 message listener |
| `frontend/src/components/chat/ChatWindow.tsx` | `useAppBadge`/`clearAppBadge` | `markAllSeen` clears both badges | ✓ WIRED | line 62 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `useAppBadge(unreadCount)` in `ChatWindow.tsx` | `unreadCount` | `useUnread(allMessages.length)` — derived from real fetched message list, not hardcoded | Yes | ✓ FLOWING |
| `SettingsPage.tsx` mirror toggle | `settings.telegram_mirror_enabled` | `useQuery(['settings'], fetchSettings)` → `GET /api/settings` → `HubSettingsStore.get()` (real Firestore doc) | Yes | ✓ FLOWING |
| `push_sender.send_push_to_all` fan-out | `store.list_all()` | `PushSubscriptionStore.list_all()` — real Firestore collection query, not a static return | Yes | ✓ FLOWING |
| `_check_push_health` | `subscriptions`, `settings` | Real `PushSubscriptionStore.list_all()` / `HubSettingsStore.get()` calls, not stubbed | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `pywebpush` importable | `.venv/bin/python -c "import pywebpush"` | No error | ✓ PASS |
| Frontend build produces injectManifest custom SW | `npm run build` | `mode injectManifest`, `dist/sw.js`, 13 precache entries generated | ✓ PASS |
| Backend full test suite | `.venv/bin/python -m pytest -q --deselect tests/test_autonomous.py::TestPhase28HabitGather::test_habit_gather_dedups_already_nudged` | `1654 passed, 3 skipped, 1 deselected` | ✓ PASS |
| Frontend unit tests | `npx vitest run` | `17 test files, 103 tests passed` | ✓ PASS |
| Frontend type-check | `npx tsc -b --force` | No output (clean) | ✓ PASS |
| `send_push_to_all` unit tests (isolated) | `.venv/bin/python -m pytest tests/test_push_sender.py -v` | `16 passed` | ✓ PASS |
| Live cron push classes | `grep -n "message_class=" core/{morning_briefing,nightly_review,heartbeat,weekly_training_review}.py` | briefing→`briefing`, nightly/weekly review→`review`, heartbeat (4x)→`alert` | ✓ PASS |
| No `disable_notification` anywhere in send paths | `grep -rn disable_notification core/scheduled_message.py interfaces/` | Only appears in comments, never as an actual kwarg | ✓ PASS |

Note: an ad-hoc subset run of 6 test files together (excluding `test_tools.py`, whose collection has a known unrelated import-order interaction) intermittently showed 2 failures that did NOT reproduce when the same files ran inside the full suite or individually — a pre-existing test-collection-order artifact (see MEMORY.md "Test isolation root cause"), not a Phase 29 defect. The authoritative full-suite run (documented above) is 100% green.

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared or found for this phase. Step 7c: SKIPPED (no probes declared).

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|--------------|--------------|--------------|--------|----------|
| PUSH-01 | 29-01, 29-03, 29-06, 29-09, 29-10 | Enable push from a button (user gesture); stored in `PushSubscriptionStore`; re-validated on hub open | ✓ SATISFIED | `usePush.ts`, `/api/push/subscribe`, `PushSubscriptionStore`, `SettingsPage.tsx` |
| PUSH-02 | 29-01, 29-02, 29-04, 29-07, 29-08 | Replies + proactive messages arrive as push when app closed, `event.waitUntil` wrapped, verified on physical device | ✓ SATISFIED (code) / pending device witness (D-20) | `sw.ts` push handler, `send_and_inject` all 3 paths, `push_sender.py` |
| PUSH-03 | 29-03, 29-05, 29-06, 29-08 | Proactive messages mirror to Telegram behind a flag, mirror runs >=1 week before disable | ✓ SATISFIED (code) / pending 1-week observation (D-21) | `HubSettingsStore`, `toggle_telegram_mirror`, `send_and_inject` mirror gate |
| PUSH-04 | 29-02, 29-07, 29-09, 29-10 | Installed icon shows unread-count badge via Badging API | ✓ SATISFIED | `useAppBadge.ts`, `sw.ts` badge increment |

No orphaned requirements — `.planning/REQUIREMENTS.md` maps exactly PUSH-01..04 to Phase 29, and all four appear in at least one plan's `requirements:` frontmatter field. (REQUIREMENTS.md traceability table still shows "Pending" status text for all four — this is a documentation-update step that normally accompanies phase close, not a code gap.)

### Anti-Patterns Found

None. Scanned all Phase 29 modified files (`core/push_sender.py`, `core/scheduled_message.py`, `core/tools.py`, `core/heartbeat.py`, `memory/firestore_db.py`, `interfaces/web_server.py`, `interfaces/_router.py`, `frontend/src/sw.ts`, `frontend/vite.config.ts`, `frontend/src/hooks/usePush.ts`, `frontend/src/hooks/useAppBadge.ts`, `frontend/src/components/settings/SettingsPage.tsx`, `frontend/src/components/shared/PushEnableBanner.tsx`, `frontend/src/App.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/chat/ChatWindow.tsx`, `frontend/src/components/timeline/TimelineHeader.tsx`) for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` and "not yet implemented"/"coming soon" patterns — zero matches.

Code review (`29-REVIEW.md`) found 1 critical + 7 warnings + 9 info. The critical (CR-01) and 3 of 7 warnings (WR-01, WR-02, WR-03, WR-06 — actually 4 warnings) were fixed in a dedicated fix pass (commits `f171e62`, `f9dfa55`, `019308e`, `d1e555a`, `4c5b30f`) — all five fixes verified live in the current codebase during this verification (see Plan-Level Must-Haves rows 11, 27, 31 and the code excerpts inspected directly).

### Deferred Findings (intentionally out of scope for this phase)

| Finding | Reason deferred |
|---------|------------------|
| WR-04 (inline-keyboard training check-ins become undeliverable once mirror is off) | Post-mirror-week concern by design (D-11/D-21) — the mirror is still ON; this only bites after Amit flips it off, which is explicitly a later, separate decision |
| WR-05 (total push-delivery failure invisible to callers once mirror is off) | Same as WR-04 — only matters after mirror retirement |
| WR-07 (heartbeat quiet-hours queue overwrite loses queued criticals) | Pre-existing bug outside Phase 29 scope (heartbeat code predates this phase); Phase 29 only added a new signal type that flows through the same pre-existing mechanism |
| IN-01 through IN-09 | Info-severity, no user-facing behavior change; left as documented follow-ups in `29-REVIEW.md` |

### Human Verification Required

### 1. D-20 #1 — Enable-push flow on physical iPhone

**Test:** From the Settings page or the Today banner, tap "Enable push"; observe the iOS permission prompt.
**Expected:** Permission prompt appears from the real user gesture; granting it results in a subscription document in Firestore `push_subscriptions` (confirmable via the `get_push_health` brain tool).
**Why human:** Requires a live iOS Safari/PWA permission dialog and a physical tap — not exercisable in CI or via static analysis.

### 2. D-20 #2 — Chat-reply push with app fully closed

**Test:** Fully close (swipe away) the installed PWA. Send Klaus a message via Telegram (or trigger a hub reply) and wait for the response.
**Expected:** The reply arrives as a lock-screen push notification.
**Why human:** Real APNs delivery to a backgrounded/terminated PWA cannot be observed from source code.

### 3. D-20 #3 — Proactive push with app fully closed

**Test:** With the app fully closed, wait for (or manually trigger) an autonomous-tick outreach or a cron send (briefing/nightly review).
**Expected:** The proactive message arrives as a push notification.
**Why human:** Same reasoning as #2 — requires witnessing real device delivery.

### 4. D-20 #4 — Icon unread badge

**Test:** After a closed-app push arrives, look at the installed home-screen icon; then open the app and view chat.
**Expected:** The icon shows an unread-count badge after the closed-app push; opening + viewing chat clears both the in-app counter and the icon badge.
**Why human:** Home-screen icon badge rendering is an OS-level visual effect, not observable from code.

### 5. D-21 — One-week Telegram-mirror production observation

**Test:** Leave `telegram_mirror_enabled` ON for at least 7 days of real usage; daily-audit that every Telegram message has a matching push (no unexplained lone Telegram buzzes).
**Expected:** Zero unexplained missing pushes across the observation window before Amit makes the mirror-off decision.
**Why human:** This is a calendar-time production-reliability observation, not a static code property. Tracked in `29-HUMAN-UAT.md` Section 2 (deliberately left open past this phase's code-complete point per D-21).

### Gaps Summary

No blocking gaps found. All 4 requirement IDs (PUSH-01..04) are implemented and wired end-to-end: the VAPID-signed Web Push pipeline exists from Secret Manager through `send_push_to_all`, all three outbound send paths (Telegram-turn reply, hub chat reply, proactive crons) fan out pushes via `run_in_executor`, the Telegram mirror is gated by a real Firestore-backed flag defaulting ON, Klaus has two self-awareness tools plus a heartbeat checker, and the frontend has a complete subscribe/re-validate/badge/settings/banner surface backed by a hand-written injectManifest service worker. The 5 code-review fixes (CR-01, WR-01, WR-02, WR-03, WR-06) were independently re-verified in the current source, not just trusted from the Fix Log. Backend (1654 tests) and frontend (103 tests + tsc + build) are green.

The phase's own design (10-plan roadmap) intentionally ends on a physical-device UAT gate (D-20) and a post-phase mirror-week tracking period (D-21) that cannot be completed by a code verifier — these route to Human Verification per the phase's explicit closing criteria, not to gaps.

---

_Verified: 2026-07-05_
_Verifier: Claude (gsd-verifier)_
