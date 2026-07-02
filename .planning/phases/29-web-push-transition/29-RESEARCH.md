# Phase 29: Web Push & Transition - Research

**Researched:** 2026-07-02
**Domain:** iOS PWA Web Push (VAPID) + service-worker migration + Telegram-mirror transition
**Confidence:** HIGH (iOS push mechanics, pywebpush, injectManifest recipe) / MEDIUM (notificationclick navigation on iOS, badge-count sync mechanics)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Push scope & foreground policy
- **D-01:** **Everything Klaus sends pushes.** Chat replies + every proactive cron +
  habit nudges — one consistent channel; all sends already flow through
  `core/scheduled_message.py::send_and_inject`, which gains push delivery (per the
  locked design spec). Hub chat replies (which bypass `send_and_inject` today via
  `/internal/process-hub-message`) must also trigger push.
- **D-02:** **Suppress push only when the chat view itself is visible.** If the app
  is open on Today/Tasks/etc., the banner still fires (Amit explicitly chose "push
  unless chat is visible" over app-wide suppression). Only an actively visible chat
  suppresses.
- **D-03:** **No server-side quiet hours.** Pushes always send; iOS Focus modes do
  the overnight silencing. The nightly review push simply waits on the lock screen.
- **D-04:** **Failure handling: mirror now, loud logging later.** During transition
  the Telegram mirror is the safety net. Post-retirement: push-send failures log
  loudly and surface via heartbeat-style alerting (see D-14 — built THIS phase);
  the hub re-validates/re-subscribes on next open. Messages are never lost — they
  are always in the Firestore conversation.
- **D-05:** **Interactive Telegram flows (training check-in inline keyboards,
  autonomous follow-up buttons) push as plain text**; Amit responds conversationally
  in hub chat ("logged it", "skip"). Telegram keeps its buttons while the mirror is
  on. Hub-native tappable check-in UI is deferred (see Deferred Ideas).
- **D-06:** **No daily push cap.** Existing judgment (tick-brain triage,
  repeat-suppression, `CoachingTopicStore` dedup) is the volume control — same
  message volume as Telegram today, new channel.
- **D-07:** **Per-class TTL.** Time-critical classes (leave-by/traffic alerts,
  habit-slot nudges) expire after ~an hour if undeliverable; briefings, reviews,
  and chat replies persist until delivered. Exact TTL values → Claude's discretion.

#### Telegram mirror & retirement
- **D-08:** **Everything mirrors during transition** — every Klaus send goes to BOTH
  push and Telegram while the flag is on (broader than PUSH-03's "proactive"
  wording; deliberate). The complete Telegram thread doubles as the audit trail for
  push completeness.
- **D-09:** **Mirror flag is a runtime Firestore toggle** (settings doc — e.g., a
  small config/settings store or SelfState field), flippable from the hub Settings
  page or by telling Klaus (D-13), effective immediately, no deploy. NOT an env var.
- **D-10:** **Both channels notify at full volume during the mirror week.** No
  `disable_notification` on the mirror — Amit explicitly wants the double-buzz: a
  lone Telegram buzz immediately reveals a missing push.
- **D-11:** **Retirement = path only, removal later.** This phase ships push +
  mirror + flag. After ≥1 trusted week Amit flips the mirror off; Telegram stays
  dormant-but-working (webhook intact — it remains an input channel, including
  photo upload, which the hub does not replace this phase). Actual code removal is
  a future cleanup decision — mirrors the Phase-27 TickTick order: verified → then
  remove.

#### Notification content & tap behavior
- **D-12:** Title **"Klaus"** + **full message text** (iOS truncates/expands).
  **Tap always opens the Today timeline** (home) — NOT the chat, NOT
  context-dependent deep links; the unread badge guides Amit to chat.
  **Each message is its own notification** — no `tag` replacement; iOS stacks by
  app. **Standard sound/vibration** — Klaus behaves like any messaging app; Amit
  tunes it system-side if needed.

#### Klaus's own push awareness
- **D-13:** **Two brain-direct tools:** (a) toggle the Telegram-mirror flag, and
  (b) read push health — subscription present/valid, last successful push, mirror
  state. Amit can execute the retirement decision conversationally ("kill the
  mirror"). Follows the `get_self_status` self-aware pattern.
- **D-14:** **Push-failure alerting is built THIS phase**, wired into the existing
  heartbeat/alert machinery — it self-validates during the mirror week (failures
  visible while Telegram still covers delivery), so retirement is just flipping the
  flag with no follow-up build step.

#### Enable UX & badge semantics
- **D-15:** **New minimal Settings page** hosting exactly this phase's controls:
  enable-push status/button + Telegram-mirror toggle. Nothing else (no sign-out
  etc.) — a skeleton future phases can grow into. Nav placement (gear icon etc.) →
  Claude's discretion.
- **D-16:** **First-run dismissible banner on Today** prompting push enable —
  mirrors the Phase-26 iOS install-banner pattern. iOS requires the actual
  subscribe call to come from a user gesture.
- **D-17:** **iPhone-first, store supports many.** `PushSubscriptionStore` +
  endpoints handle multiple subscriptions from day one (fan-out on send, per-
  subscription cleanup), but only the iPhone is actively enabled + physically
  verified this phase. Desktop can subscribe later with zero backend change.
- **D-18:** **Icon badge mirrors the in-app unread counter** — one source of truth:
  unread Klaus messages since the chat was last viewed. Push arrivals increment it
  while the app is closed (service-worker `setAppBadge`); opening the chat clears
  both the tab badge and the icon badge together (existing `useUnread` /
  `markAllSeen` is the anchor).
- **D-19:** **Dead-subscription recovery is silent.** On hub open, if permission is
  still granted but the subscription is stale/revoked → quietly re-subscribe in the
  background and update the store. Only if notification permission itself was
  revoked does a banner appear explaining the iOS Settings fix.

#### Verification & rollout sequencing
- **D-20:** **Phase closes on physically verified push with the mirror ON:**
  enable flow → one chat-reply push (app closed) → one real proactive push
  (autonomous tick or manually-triggered cron) → icon badge — all witnessed on the
  iPhone. All classes share the `send_and_inject` pipe, so two witnessed classes
  prove it; the mirror week catches stragglers.
- **D-21:** **The 1-week mirror observation + the mirror-off decision live in
  `29-HUMAN-UAT.md`** as tracked post-phase items — same pattern as Phase 26's
  on-device items. The phase does NOT stay open for the calendar week.

### Claude's Discretion
- `PushSubscriptionStore` document shape, VAPID key management (Secret Manager),
  and the web-push send library (e.g., `pywebpush`) + 404/410 subscription cleanup.
- Service-worker strategy change: the frontend currently uses vite-plugin-pwa
  `generateSW` — adding a `push`/`notificationclick` handler will need
  `injectManifest` (or equivalent); preserve the existing update-prompt +
  runtime-caching behavior exactly.
- How chat-view visibility is tracked for D-02 suppression (client heartbeat,
  visibility flag on poll, or SW-side check) — pick what iOS PWAs support reliably.
- Exact per-class TTL values (D-07) and the message-class taxonomy passed to the
  push sender.
- Unread-count synchronization mechanics between server, push payload, and
  `useUnread` (D-18) — including keeping the count correct when the app is closed.
- Push-failure alert thresholds/wording in the heartbeat integration (D-14).
- Async handling of push sends inside crons — do NOT block the event loop (see the
  weekly-review 500 incident; Pitfall 2 class).
- Settings page layout/visuals + banner design (D-15/D-16).

### Deferred Ideas (OUT OF SCOPE)
- **Hub-native interactive check-in UI** (tappable log/skip/snooze cards in hub
  chat replacing Telegram inline keyboards) — future phase; until then check-ins
  push as text and are answered conversationally (D-05).
- **Actual Telegram code removal** (bot, webhook, `_router.py`, mirror plumbing) —
  future cleanup decision after ≥1 trusted mirror week; note the hub has no photo
  input yet, so Telegram remains the photo channel until that gap is addressed.
- **Desktop push enablement + verification** — backend supports it from day one
  (D-17); actively enabling/verifying desktop is post-phase.
- **Server-side quiet hours / daily push caps** — rejected (D-03/D-06); revisit
  only if push volume becomes a real problem.
- **Settings page growth** (sign-out, preferences, app version) — deliberately kept
  off the skeleton page this phase (D-15).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUSH-01 | Enable push from a button (user gesture) in the installed PWA; subscriptions stored in `PushSubscriptionStore`, re-validated on hub open | Pattern 3 (subscribe flow + iOS gesture requirement), Pattern 2 (`PushSubscriptionStore` shape), Pattern 8 (re-validation / D-19 silent recovery) |
| PUSH-02 | Replies + proactive messages arrive as push when app closed; `event.waitUntil` wrapped; verified on physical iPhone | Pattern 1 (delivery pipeline through `send_and_inject` + all three send paths), Pattern 4 (SW push handler, waitUntil, silent-push penalty), Pattern 5 (pywebpush non-blocking fan-out), Pitfalls 1–3 |
| PUSH-03 | Proactive messages mirror to Telegram behind a flag, ≥1 week before disable | Pattern 1 (mirror flag in `HubSettingsStore`, D-08 everything mirrors), Pattern 9 (D-13 brain tools + D-14 heartbeat alerting) |
| PUSH-04 | Installed icon shows unread-count badge via the Badging API | Pattern 6 (SW `setAppBadge` + IndexedDB counter + `useUnread` reconciliation), verified iOS 16.4+ support |
</phase_requirements>

## Summary

Phase 29 has three technical centers of gravity, and all three have well-trodden, verified solutions:

1. **iOS Web Push is strict but fully supported.** Push works only in the installed (home-screen) PWA on iOS 16.4+, the subscribe call must come from a user gesture, `userVisibleOnly: true` is mandatory, and — critically — **Safari revokes the push subscription after 3 "silent" pushes** (a push where the SW fails to display a notification, including forgetting `event.waitUntil`). This makes D-02's chat-visibility suppression a server-side decision, NOT a service-worker decision: if the SW receives a push and doesn't show a notification, it burns a strike. The reliable iOS design is: the client reports chat visibility on its existing 2.5s `/api/chat/messages` poll; the server skips the push send entirely when chat is visible. `[VERIFIED: webkit.org + dev.to/progressier 3-strikes writeup]`

2. **The `generateSW` → `injectManifest` migration is a documented recipe** (vite-plugin-pwa official docs): flip `strategies`, point at `src/sw.ts`, then in the custom SW replicate the three load-bearing behaviors — `precacheAndRoute(self.__WB_MANIFEST)` + `cleanupOutdatedCaches()` (precache), the `SKIP_WAITING` message listener (which is exactly what `useRegisterSW`'s `updateServiceWorker(true)` posts — the UpdatePrompt flow survives unchanged), and the two `registerRoute` calls that replicate the current `runtimeCaching` config (NetworkFirst html-cache with 5s timeout = HUB-03; CacheFirst assets-cache). All `workbox-*` packages are already in the lockfile at 7.4.1 as vite-plugin-pwa transitive deps — they just become direct devDependencies. `[CITED: vite-pwa-org.netlify.app/guide/inject-manifest]`

3. **`pywebpush` (v2.3.0, web-push-libs org) is the standard Python sender.** It is synchronous (requests-based), so every send inside an async cron/route MUST go through `loop.run_in_executor` with an explicit `timeout=` — the same class of bug as the weekly-review 500 incident. 404/410 responses mean the subscription is dead and must be deleted from `PushSubscriptionStore`. VAPID private key lives in Secret Manager (existing `SecretManagerTokenStorage` pattern in `core/auth_google.py`); the public key is served to the frontend via a session-auth endpoint so it stays env-driven.

**Primary recommendation:** Build one new async delivery function in `core/scheduled_message.py` (push fan-out via executor + mirror-flag Telegram send + conversation inject), route all three Klaus send paths through it (crons via `send_and_inject`, hub replies in `/internal/process-hub-message`, Telegram-turn replies at `_router.py:362`), do D-02 suppression server-side, and keep the SW push handler dead simple: always `event.waitUntil(showNotification + setAppBadge)`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Push subscription (subscribe/permission) | Browser/PWA client | API (`/api/push/*` persistence) | iOS requires user-gesture subscribe in the installed PWA; only the client can call `pushManager.subscribe` |
| Subscription storage + validation | API/Backend (Firestore `PushSubscriptionStore`) | Client (re-validate on open) | Server owns the fan-out list; client detects staleness on open (D-19) |
| Push sending (VAPID, encryption, TTL) | API/Backend (`pywebpush` in `core/`) | — | Payload encryption + VAPID signing are server responsibilities; keys never reach the client |
| D-02 chat-visibility suppression | API/Backend (visibility flag from poll) | Client (reports visibility) | SW-side suppression = silent push = iOS 3-strikes revocation; must decide before sending |
| Notification display + badge increment | Service Worker | — | Only the SW runs when the app is closed; `event.waitUntil` mandatory |
| Notification tap → Today | Service Worker (`notificationclick`) | Client (router navigation via postMessage) | SW focuses/opens window; in-page router handles the route |
| Unread badge (icon) | Service Worker (closed) + Client (open) | — | SW increments while closed; client reconciles from `useUnread` on open/visibility |
| Telegram mirror flag | Backend (Firestore settings doc) | Client (Settings toggle) + Brain tool (D-13) | Runtime toggle, no deploy (D-09); three writers, one store |
| Push-failure alerting | Backend (`core/heartbeat.py`) | — | Extends existing Signal/tier machinery (D-14) |
| Settings page + enable banner | Frontend (React) | — | New `/settings` route + Today banner (D-15/D-16) |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pywebpush` | 2.3.0 (PyPI, verified 2026-07-02) | Web Push payload encryption (aes128gcm) + VAPID-signed sends | The web-push-libs reference Python implementation (same org as the Node `web-push` lib); wraps py-vapid + http-ece `[ASSUMED — slopcheck unavailable; see audit]` |
| `py-vapid` | 1.9.4 (PyPI, verified 2026-07-02) | VAPID key generation (one-time operator step) | Mozilla-services; pywebpush's own VAPID dependency `[ASSUMED — slopcheck unavailable; see audit]` |
| `workbox-precaching` / `workbox-routing` / `workbox-strategies` / `workbox-expiration` | 7.4.1 (npm, verified; already in lockfile as vite-plugin-pwa transitive deps) | Custom SW precache + runtime caching, replicating current generateSW behavior | Official Google Chrome team libs; exactly what generateSW compiles from `[ASSUMED — slopcheck unavailable; see audit]` |
| `idb` | 8.0.3 (npm, verified; v7 already transitively in lockfile) | Tiny IndexedDB wrapper for the SW badge counter | jakearchibald's standard IDB promise wrapper — OPTIONAL; raw IndexedDB (≈25 lines) avoids the new dep entirely `[ASSUMED]` |

### Supporting (already installed — no new packages)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `google-cloud-secret-manager` | ≥2.20 (in requirements.txt) | VAPID private-key storage | Reuse `SecretManagerTokenStorage` pattern (`core/auth_google.py:106`) |
| `vite-plugin-pwa` | 1.3.0 (in package.json) | injectManifest build of the custom SW | Same plugin, `strategies` flip only |
| `google-cloud-firestore` | ≥2.18 | `PushSubscriptionStore` + `HubSettingsStore` | Model on existing store classes in `memory/firestore_db.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pywebpush` | `webpush` (newer PyPI package, httpx-based) | Async-native, but far younger/less battle-tested; pywebpush + `run_in_executor` matches the project's existing sync-tool-in-executor pattern |
| SW IndexedDB badge counter | Server-computed count in push payload | Server doesn't know `last_seen_seq` (localStorage-only today); pushing it server-side is a bigger change than the phase needs |
| `injectManifest` custom SW | Declarative Web Push (Safari 18.4+) | Declarative push removes the silent-push penalty but is Safari-only, newer, and can't run the badge/counter logic; classic Web Push is the cross-platform standard (D-17 wants desktop-capable) |
| Serving VAPID public key via `/api/push/vapid-public-key` | Baking it into the Vite bundle via env | Endpoint keeps config env-driven (CLAUDE.md invariant) and avoids a rebuild if keys ever rotate |

**Installation:**
```bash
# Backend (add to requirements.txt)
pywebpush>=2.3
# py-vapid comes in as a pywebpush dependency; pin explicitly only if the
# operator key-gen step uses the `vapid` CLI:
py-vapid>=1.9

# Frontend (promote existing transitive deps to direct devDependencies)
cd frontend && npm install -D workbox-precaching@^7.4.1 workbox-routing@^7.4.1 workbox-strategies@^7.4.1 workbox-expiration@^7.4.1 workbox-core@^7.4.1
```

**Version verification:** `pywebpush 2.3.0` and `py-vapid 1.9.4` confirmed against PyPI JSON API 2026-07-02; `workbox-* 7.4.1`, `idb 8.0.3`, `vite-plugin-pwa 1.3.0` confirmed via `npm view` 2026-07-02.

## Package Legitimacy Audit

slopcheck could not be installed in this environment (auto-mode denied the pip install). Per the graceful-degradation rule, every package below is tagged `[ASSUMED]` and the planner must gate each *new* install behind a `checkpoint:human-verify` task. Registry metadata (age, repo, postinstall) was still gathered and is strongly reassuring:

| Package | Registry | Age | Source Repo | Postinstall | slopcheck | Disposition |
|---------|----------|-----|-------------|-------------|-----------|-------------|
| pywebpush 2.3.0 | PyPI | ~9 yrs (web-push-libs) | github.com/web-push-libs/pywebpush | n/a | unavailable | [ASSUMED] — gate install |
| py-vapid 1.9.4 | PyPI | ~9 yrs (mozilla-services) | github.com/mozilla-services/vapid | n/a | unavailable | [ASSUMED] — gate install |
| workbox-precaching 7.4.1 | npm | created 2017 (googlechrome/workbox) | github.com/googlechrome/workbox | none | unavailable | [ASSUMED] — already in lockfile (transitive) |
| workbox-routing / strategies / expiration / core 7.4.1 | npm | 2017–2019 | github.com/googlechrome/workbox | none | unavailable | [ASSUMED] — already in lockfile (transitive) |
| idb 8.0.3 | npm | created 2015 | github.com/jakearchibald/idb | none | unavailable | [ASSUMED] — OPTIONAL; recommend raw IndexedDB instead to avoid the new dep |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged [SUS]:** none (no postinstall scripts found on any npm package above; all have decade-scale history and official-org repos)

**Cross-ecosystem check:** `pywebpush`/`py-vapid` verified on PyPI (not npm); workbox/idb verified on npm — no cross-ecosystem confusion.

## Architecture Patterns

### System Architecture Diagram

```
                        KLAUS SEND PATHS (all three must push — D-01)
  ┌───────────────────┐   ┌─────────────────────────┐   ┌──────────────────────────┐
  │ Proactive crons    │   │ /internal/process-hub-  │   │ Telegram webhook turn     │
  │ (autonomous, night │   │ message (hub chat reply)│   │ (_router.py:362           │
  │ review, briefing,  │   │                         │   │  reply_text)              │
  │ heartbeat, habits) │   │                         │   │                           │
  └─────────┬─────────┘   └───────────┬─────────────┘   └────────────┬─────────────┘
            │ send_and_inject          │                              │
            ▼                          ▼                              ▼
  ┌─────────────────────────────────────────────────────────────────────────────────┐
  │        core/scheduled_message.py — unified delivery (NEW: deliver + mirror)     │
  │                                                                                 │
  │  1. D-02 gate: chat visible? (HubSettingsStore.chat_visible_until > now)        │
  │     └─ visible → SKIP push (server-side; never a silent push)                   │
  │  2. Push fan-out: PushSubscriptionStore.list() → for each sub:                  │
  │     run_in_executor( pywebpush.webpush(sub, payload, ttl=CLASS_TTL,             │
  │                       timeout=10) )                                             │
  │     ├─ 404/410 → delete subscription; log                                       │
  │     └─ success → stamp last_success_at                                          │
  │  3. Mirror gate: HubSettingsStore.telegram_mirror_enabled?                      │
  │     └─ ON → bot.send_message (full volume, D-10)                                │
  │  4. Conversation inject (unchanged)                                             │
  └────────────────────────────────────┬────────────────────────────────────────────┘
                                       │  encrypted push via APNs web push gateway
                                       ▼
  ┌─────────────────────────────────────────────────────────────────────────────────┐
  │  frontend/src/sw.ts (custom SW, injectManifest)                                 │
  │                                                                                 │
  │  precacheAndRoute(self.__WB_MANIFEST) + cleanupOutdatedCaches()   (HUB-03)      │
  │  registerRoute(document → NetworkFirst html-cache, 5s timeout)    (HUB-03)      │
  │  registerRoute(/assets/ → CacheFirst assets-cache)                              │
  │  message {SKIP_WAITING} → self.skipWaiting()                (UpdatePrompt flow) │
  │                                                                                 │
  │  push → event.waitUntil( incrementBadge(IDB) ; setAppBadge(n) ;                 │
  │                          showNotification("Klaus", {body}) )   ← ALWAYS shows   │
  │  notificationclick → event.waitUntil( focus existing client → postMessage       │
  │                          {NAVIGATE:'/'}  ∥  openWindow('/') )      (D-12 Today) │
  └────────────────────────────────────┬────────────────────────────────────────────┘
                                       │ app open
                                       ▼
  ┌─────────────────────────────────────────────────────────────────────────────────┐
  │  React app: useUnread (localStorage seq) ⇄ navigator.setAppBadge reconcile      │
  │  markAllSeen → clearAppBadge() + postMessage {RESET_BADGE} to SW    (D-18)      │
  │  /settings page: enable-push button (gesture) + mirror toggle      (D-15)       │
  │  Today banner: first-run enable prompt (InstallBanner pattern)     (D-16)       │
  │  On mount: permission granted + no subscription → silent resubscribe (D-19)     │
  └─────────────────────────────────────────────────────────────────────────────────┘

  Firestore: push_subscriptions/* (PushSubscriptionStore)  ·  config/hub_settings
  Secret Manager: klaus-vapid-private-key   ·  env: VAPID_PUBLIC_KEY (or SM too)
  Heartbeat: _check_push_health() → Signal(fingerprint="push:...") (D-14)
  Brain tools: toggle_telegram_mirror + get_push_health (D-13, core/tools.py)
```

### Recommended Project Structure

```
core/
├── scheduled_message.py   # MODIFIED: push fan-out + mirror flag + message_class
├── push_sender.py         # NEW: pywebpush wrapper, per-class TTL, 404/410 cleanup
├── heartbeat.py           # MODIFIED: _check_push_health() checker (D-14)
├── tools.py               # MODIFIED: toggle_telegram_mirror + get_push_health tools
memory/
└── firestore_db.py        # MODIFIED: PushSubscriptionStore + HubSettingsStore
interfaces/
├── web_server.py          # MODIFIED: /api/push/* + /api/settings routes;
│                          #   push hooks in /internal/process-hub-message
└── _router.py             # MODIFIED: push after reply_text (line 362 path)
frontend/
├── vite.config.ts         # MODIFIED: strategies 'injectManifest', srcDir, filename
├── tsconfig (app)         # MODIFIED: lib += "WebWorker"
└── src/
    ├── sw.ts              # NEW: custom service worker (see Pattern 4)
    ├── hooks/usePush.ts   # NEW: subscribe / re-validate / permission state
    ├── hooks/useAppBadge.ts # NEW: badge reconciliation with useUnread (D-18)
    └── components/
        ├── settings/SettingsPage.tsx  # NEW: /settings (D-15)
        └── shared/PushEnableBanner.tsx # NEW: Today banner (D-16, InstallBanner pattern)
```

### Pattern 1: Unified delivery with mirror flag (backend heart)

**What:** `send_and_inject` grows push delivery + mirror gating; all three send paths converge.
**When to use:** Every Klaus outbound message.

Key facts from the codebase:
- `send_and_inject(bot, text, *, inject_into_conversation, reply_markup)` currently: Telegram send → optional Firestore inject (`core/scheduled_message.py:26`). Callers: proactive_alerts, morning_briefing, weekly_training_review, training_checkin, nightly_review, autonomous, heartbeat.
- Hub replies: `/internal/process-hub-message` appends the assistant reply to the conversation with **no Telegram send** — needs a push hook (and, per D-08 "everything mirrors", a Telegram mirror send while the flag is on).
- Telegram-turn replies: `interfaces/_router.py:362` `await update.message.reply_text(orchestrator_response)` — this is the third send path; D-01 says these push too. (The Telegram send already happened natively here; only push is added.)

Recommended shape (signature stays backward-compatible; new keyword-only params):

```python
# core/scheduled_message.py — conceptual sketch
async def send_and_inject(
    bot, text, *,
    inject_into_conversation=False,
    reply_markup=None,
    message_class="default",          # NEW: drives TTL (D-07)
    push=True,                        # NEW: _router reply path passes telegram=False instead
) -> "telegram.Message | None":
    settings = await loop.run_in_executor(None, _get_hub_settings)  # small cached read
    # 1. Push fan-out (never blocks the loop — Pitfall 2 class)
    if push and not _chat_visible(settings):
        await loop.run_in_executor(None, send_push_to_all, text, message_class)
    # 2. Telegram (mirror-gated for cron/hub paths; native for _router path)
    msg = None
    if settings.get("telegram_mirror_enabled", True):
        msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    # 3. Conversation inject (unchanged)
    ...
```

**D-10 OutreachLog gate interaction:** today the append is gated on `send_and_inject` success. New rule the planner must lock in: **success = delivered to at least one channel** (push accepted by ≥1 subscription OR Telegram send succeeded). During the mirror week both usually succeed; post-retirement push alone counts. A total failure (no channels) → no OutreachLog entry, preserved semantics.

**Mirror-flag read cost:** D-09 requires effective-immediately. One Firestore doc read per send is fine at Klaus's volume (≤ ~40 sends/day); a 30s in-process cache is acceptable if desired, but do NOT cache longer.

### Pattern 2: `PushSubscriptionStore` + `HubSettingsStore` (Firestore)

**What:** Two new stores in `memory/firestore_db.py`, modeled on existing classes.

```python
# Collection: push_subscriptions   doc id = sha256(endpoint).hexdigest()[:32]
{
    "endpoint": "https://web.push.apple.com/...",
    "keys": {"p256dh": "...", "auth": "..."},
    "user_agent": "...",                    # device label for push-health tool
    "created_at": SERVER_TIMESTAMP,
    "last_validated_at": SERVER_TIMESTAMP,  # stamped by /api/push/subscribe upsert
    "last_success_at": SERVER_TIMESTAMP,    # stamped on accepted send
    "failure_count": 0,                     # reset on success; ++ on non-404/410 error
    "last_error": None,
}
# Methods: upsert(sub_json, user_agent), list_all(), delete(endpoint),
#          record_success(endpoint), record_failure(endpoint, error)

# Doc: config/hub_settings  (HubSettingsStore — mirror HeartbeatConfigStore get/update)
{
    "telegram_mirror_enabled": True,        # D-08/D-09; default ON
    "push_enabled_at": SERVER_TIMESTAMP,    # first successful subscribe (health tool)
    "chat_visible_until": None,             # D-02 suppression window (ISO or ts)
    "updated_at": SERVER_TIMESTAMP,
}
```

Follow the house rules: `_jsonsafe_doc` on every read that feeds `json.dumps` (DatetimeWithNanoseconds pitfall), doc-level-only SERVER_TIMESTAMP, `updated_at` on merge writes.

### Pattern 3: Subscribe flow + VAPID key management (PUSH-01)

**iOS hard requirements** `[VERIFIED: webkit.org "Meet Web Push" + Apple docs via search]`:
- Push API exists ONLY in the installed home-screen web app (iOS 16.4+; Israel is non-EU so standalone install works — established in Phase 26).
- `pushManager.subscribe` (which triggers the permission prompt) MUST be called from a user-gesture handler — a button tap. Calling it on mount silently fails/denies.
- `userVisibleOnly: true` is mandatory.

```ts
// frontend/src/hooks/usePush.ts — subscribe (called from the Settings/banner button)
async function enablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.ready
  const { key } = await api.get('/api/push/vapid-public-key')  // session-auth
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  })
  await api.post('/api/push/subscribe', {
    subscription: sub.toJSON(),           // {endpoint, keys:{p256dh, auth}}
    user_agent: navigator.userAgent,
  })
}
// Feature-detect first: 'serviceWorker' in navigator && 'PushManager' in window
// && 'Notification' in window. Not installed → show install banner instead.
```

**VAPID key generation (one-time operator step, documented in 29-USER-SETUP or DEPLOYMENT.md):**
```bash
pip install py-vapid
vapid --gen                    # writes private_key.pem + public_key.pem
vapid --applicationServerKey   # prints the base64url public key for the frontend
# Store private key: Secret Manager secret `klaus-vapid-private-key` (lowercase klaus-!)
gcloud secrets create klaus-vapid-private-key --data-file=private_key.pem
```
Server loads the private key at first send via the existing `SecretManagerTokenStorage`-style read (`core/auth_google.py:134` pattern — `access_secret_version` on `latest`), caches it in-process. Public key exposed via `GET /api/push/vapid-public-key` (session-auth) OR `VAPID_PUBLIC_KEY` env var read by that endpoint — endpoint approach keeps everything env/SM-driven per CLAUDE.md.

`vapid_claims["sub"] = "mailto:amit.grupper@gmail.com"`. `aud` is auto-derived from the endpoint by pywebpush; `exp` auto-set (12h). Note: pywebpush **mutates the claims dict** — pass a fresh copy per send. `[CITED: github.com/web-push-libs/pywebpush README]`

### Pattern 4: Custom service worker (`injectManifest` migration) — the HUB-03-preserving recipe

**vite.config.ts changes:**
```ts
VitePWA({
  registerType: 'prompt',        // UNCHANGED — UpdatePrompt flow preserved
  injectRegister: false,         // UNCHANGED — useRegisterSW owns registration
  strategies: 'injectManifest',  // CHANGED from 'generateSW'
  srcDir: 'src',
  filename: 'sw.ts',
  injectManifest: {
    // globPatterns moves here from `workbox` (same value)
    globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
  },
  // DELETE the `workbox` block — runtimeCaching now lives IN the SW
  manifest: { /* unchanged */ },
})
```
`[CITED: vite-pwa-org.netlify.app/guide/inject-manifest]` — with `injectManifest`, `runtimeCaching` in plugin config is IGNORED; routes must be registered in the SW file (`[CITED: github.com/vite-pwa/vite-plugin-pwa issue #626]`).

**src/sw.ts — full skeleton preserving current behavior exactly:**
```ts
/// <reference lib="webworker" />
declare let self: ServiceWorkerGlobalScope

import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching'
import { registerRoute } from 'workbox-routing'
import { NetworkFirst, CacheFirst } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'

// ── 1. Precache (replaces generateSW globPatterns behavior) ──
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// ── 2. Runtime caching — EXACT replica of vite.config.ts runtimeCaching ──
// HUB-03: index.html network-first, 5s timeout — stale-deploy protection
registerRoute(
  ({ request }) => request.destination === 'document',
  new NetworkFirst({
    cacheName: 'html-cache',
    networkTimeoutSeconds: 5,
    plugins: [new ExpirationPlugin({ maxEntries: 5, maxAgeSeconds: 60 * 60 * 24 })],
  }),
)
registerRoute(
  /\/assets\/.+\.(js|css)$/,
  new CacheFirst({
    cacheName: 'assets-cache',
    plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 365 })],
  }),
)
// NOTE: cacheableResponse {statuses:[0,200]} from the old config is the workbox
// default for these strategies on same-origin; add CacheableResponsePlugin
// explicitly if the plan-checker wants byte-for-byte parity.

// ── 3. Prompt-mode update flow (replaces generateSW's built-in listener) ──
// useRegisterSW's updateServiceWorker(true) posts {type:'SKIP_WAITING'} to the
// waiting SW — this listener is what makes the existing UpdatePrompt keep working.
self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting()
})

// ── 4. Push (PUSH-02) — ALWAYS show a notification (iOS 3-strikes) ──
self.addEventListener('push', (event) => {
  const data = (() => { try { return event.data?.json() ?? {} } catch { return {} } })()
  event.waitUntil((async () => {
    const count = await incrementBadgeCount()          // IndexedDB counter (Pattern 6)
    if ('setAppBadge' in navigator) await navigator.setAppBadge(count)
    await self.registration.showNotification(data.title ?? 'Klaus', {
      body: data.body ?? 'New message from Klaus',
      icon: '/icon-192.png',
      data: { url: data.url ?? '/' },                  // D-12: always Today
      // NO tag (D-12: each message its own notification)
    })
  })())
})

// ── 5. Tap → Today (D-12) ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil((async () => {
    const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const client = clientList[0]
    if (client) {
      await client.focus()
      client.postMessage({ type: 'NAVIGATE', path: '/' })  // react-router handles it
    } else {
      await self.clients.openWindow('/')
    }
  })())
})
```

**tsconfig:** add `"WebWorker"` to the app tsconfig `lib` array. **Vitest:** sw.ts is a new module type — exclude it from jsdom test collection or it'll fail on `self.__WB_MANIFEST`.

**Dev mode:** `devOptions: { enabled: true, type: 'module' }` only if local SW testing is wanted; not required for the build. Push can't be end-to-end tested locally on iOS anyway (needs the installed PWA over HTTPS) — physical-device UAT is the real gate (D-20).

### Pattern 5: pywebpush sends without blocking the event loop (weekly-review-500 class)

pywebpush is synchronous (`requests`). The weekly-review 500 incident (blocking gather on the loop starved the Telegram send) applies directly. `[VERIFIED: codebase STATE.md + pywebpush README]`

```python
# core/push_sender.py — sketch
from pywebpush import webpush, WebPushException

CLASS_TTL = {                      # D-07 (values = Claude's discretion, locked here)
    "leave_by": 3600,              # traffic/leave-by alerts — stale after an hour
    "habit_nudge": 3600,           # slot nudges — pointless after the slot passes
    "chat_reply": 86400,           # persist until delivered (24h is plenty; Amit
    "briefing": 86400,             #   opens his phone daily; also < APNs 28d cap)
    "review": 86400,
    "alert": 86400,                # heartbeat/system alerts
    "default": 86400,
}

def send_push_to_all(text: str, message_class: str = "default") -> dict:
    """SYNC — always call via loop.run_in_executor from async contexts."""
    store = _get_subscription_store()
    payload = json.dumps({
        "title": "Klaus",
        "body": text[:1000],       # APNs payload cap ~4KB post-encryption; be safe
        "url": "/",                # D-12
        "class": message_class,
    })
    results = {"sent": 0, "failed": 0, "removed": 0}
    for sub in store.list_all():
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                data=payload,
                vapid_private_key=_get_vapid_private_key(),   # SM-cached
                vapid_claims={"sub": "mailto:amit.grupper@gmail.com"},  # fresh dict!
                ttl=CLASS_TTL.get(message_class, CLASS_TTL["default"]),
                timeout=10,        # CLAUDE.md invariant: explicit timeout, always
            )
            store.record_success(sub["endpoint"]); results["sent"] += 1
        except WebPushException as ex:
            status = ex.response.status_code if ex.response is not None else None
            if status in (404, 410):                # dead subscription — remove
                store.delete(sub["endpoint"]); results["removed"] += 1
            else:
                store.record_failure(sub["endpoint"], f"{status}: {ex}")
                results["failed"] += 1
        except Exception as ex:                     # DNS, timeout, etc.
            store.record_failure(sub["endpoint"], str(ex)); results["failed"] += 1
    return results
```

Call sites (all async): `await loop.run_in_executor(None, send_push_to_all, text, message_class)`. With D-17's realistic subscription count (1–3 devices), sequential sends inside one executor call are fine — no need for a thread pool fan-out.

**Urgency header:** default (`normal`) is fine for all classes — every push shows a notification; APNs delivers promptly regardless. Skip the header complexity. `[ASSUMED]`

### Pattern 6: Badge sync — SW increments, client reconciles (D-18 / PUSH-04)

**Verified iOS facts** `[CITED: webkit.org/blog/14112]`: Badging API works iOS 16.4+ in home-screen web apps ONLY; available in SW context (badge on push receipt); badge appears only if notification permission granted; **a badge update alone does NOT satisfy the user-visible push requirement** — the notification must still be shown.

The current unread counter is client-only (`useUnread`: `localStorage last_seen_seq` vs `messages.length`). The SW can't read localStorage or poll the API without burning battery. Recommended two-writer, reconcile-on-open design:

- **App closed:** SW `push` handler increments a counter in IndexedDB and calls `navigator.setAppBadge(count)`.
- **App open/foregrounded:** the window recomputes truth from `useUnread` and overwrites: `navigator.setAppBadge(unreadCount)` (or `clearAppBadge()` at 0). Also posts `{type:'RESET_BADGE', count: unreadCount}` to the SW to resync the IDB counter.
- **Chat viewed (`markAllSeen` in ChatWindow's IntersectionObserver):** additionally call `navigator.clearAppBadge()` + `postMessage {RESET_BADGE, count: 0}` — this is the D-18 "one clear clears both" anchor.

Transient drift while closed (SW counts pushes; app counts messages — suppressed-while-visible sends and mirror-week Telegram-originated turns diverge slightly) self-heals on every app open. Document this as accepted behavior in the plan.

The IDB counter is ~25 lines with raw IndexedDB (`indexedDB.open('klaus-badge', 1)` → single object store, one key) — recommend raw IDB over adding the `idb` package.

### Pattern 7: D-02 suppression is SERVER-side (client-reported visibility)

**Why not SW-side:** if the SW receives a push and skips `showNotification`, iOS counts it as a silent push; **3 strikes revokes the subscription** `[VERIFIED: dev.to/progressier + webkit.org]`. SW-side suppression is therefore structurally unsafe on iOS. The decision must happen before the push is sent.

**Mechanism (reuses existing plumbing):** the hub already polls `GET /api/chat/messages` every 2–3s while chat is open (CHAT-03). Add a query param the client sets when the chat view is actually visible:

- Client: `GET /api/chat/messages?chat_visible=1` when (chat component mounted) AND `document.visibilityState === 'visible'` AND (phone: route is `/klaus`; desktop: dock chat expanded). All signals the frontend already has (ChatWindow visibility drives `markAllSeen` today).
- Server: on `chat_visible=1`, write `chat_visible_until = now + 8s` (≈3 poll intervals) — in-process module var is sufficient (single Cloud Run instance, same pattern as `_hub_user_id_cache`); Firestore field only if cross-instance safety is wanted.
- Push sender: skip the push when `now < chat_visible_until`. Telegram mirror + conversation inject still proceed.

This exactly implements D-02 (only visible chat suppresses; Today/Tasks still push) with zero iOS reliability risk and zero new polling.

**Caveat for hub replies:** when Amit sends from hub chat he's watching it, so the reply push is correctly suppressed; if he sends and immediately locks the phone, the 8s window may suppress a reply that lands 30s later — the window must be short (5–10s) and refreshed by polling so a closed app never suppresses.

### Pattern 8: Re-validation on hub open (PUSH-01 / D-19)

On app mount (or `visibilitychange` → visible), when running standalone:
```
if Notification.permission === 'granted':
    reg.pushManager.getSubscription()
      ├─ subscription exists → POST /api/push/subscribe (idempotent upsert;
      │                        stamps last_validated_at)
      └─ null (iOS revoked it, e.g. 3-strikes or expiry) →
             silently re-subscribe (NO gesture needed — permission already granted)
             → POST /api/push/subscribe
elif Notification.permission === 'denied' AND push_was_enabled (localStorage flag):
    show the "re-enable in iOS Settings > Notifications > Klaus" banner (D-19)
else:  # 'default', never asked
    show the first-run enable banner on Today (D-16)
```
Note: re-`subscribe()` without a gesture is permitted when permission is already granted — only the *permission prompt* needs the gesture. `[ASSUMED — consistent with spec behavior; verify during device UAT]`

### Pattern 9: Brain tools + heartbeat alerting (D-13 / D-14)

**Tools** (model on `get_self_status`, `core/tools.py:1788` + `_HANDLERS` at :2606 + brain-direct list at :2679):
- `toggle_telegram_mirror(enabled: bool)` → `HubSettingsStore.update({"telegram_mirror_enabled": enabled})`; returns new state. "Kill the mirror" becomes a one-tool-call action.
- `get_push_health()` → JSON: subscriptions (count, per-device user_agent, last_success_at, failure_count), mirror state, `push_enabled_at`, `chat_visible_until`. All reads via `_jsonsafe_doc`.

**Heartbeat checker** (`_check_push_health()` added to `_collect_signals`, emitting `Signal` dataclass instances like existing checkers at `core/heartbeat.py:38`):

| Condition | Fingerprint | Severity |
|-----------|-------------|----------|
| Any subscription `failure_count >= 3` | `push:failure-streak:{endpoint_hash}` | critical |
| `push_enabled_at` set but zero subscriptions in store | `push:no-subscription` | critical (post-retirement) / warning (mirror on — read the mirror flag to pick) |
| No `last_success_at` in > 48h across all subs while sends occurred | `push:delivery-stale` | warning |

Severity downgrade while `telegram_mirror_enabled` is on (Telegram covers delivery) is the self-validating property D-14 wants.

### Anti-Patterns to Avoid

- **SW-side push suppression** — silent-push strikes; see Pattern 7.
- **`registerType: 'autoUpdate'` or unconditional `self.skipWaiting()` at SW top level** — breaks the prompt-mode contract; skipWaiting must ONLY run on the `SKIP_WAITING` message.
- **Keeping `workbox.runtimeCaching` in vite.config with injectManifest** — silently ignored; HUB-03 would be lost without any build error.
- **Sending push inline in async handlers without executor** — weekly-review-500 class regression.
- **`notification.tag`/`renotify`** — D-12 forbids replacement; each message stacks.
- **Favicon badge libraries** — explicitly out of scope (REQUIREMENTS Out-of-Scope table); Badging API only.
- **Uppercase in the Secret Manager secret name** — `klaus-vapid-private-key`, lowercase (project invariant).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Push payload encryption (RFC 8291 aes128gcm) + VAPID JWT signing | Custom ECDH/HKDF crypto | `pywebpush` | Getting Web Push encryption wrong = silent delivery failures per browser vendor; pywebpush is the reference implementation |
| VAPID keypair generation | openssl incantations from blog posts | `py-vapid` CLI (`vapid --gen`, `vapid --applicationServerKey`) | Emits the exact base64url application-server-key format `PushManager.subscribe` needs |
| SW precache manifest + cache versioning | Manual cache.addAll + version strings | `workbox-precaching` (`precacheAndRoute` + `cleanupOutdatedCaches`) | Revision-hash invalidation is what makes the UpdatePrompt detect new deploys; hand-rolled versions drift |
| Runtime caching strategies | fetch-handler if/else trees | `workbox-routing` + `workbox-strategies` | The current NetworkFirst-with-timeout behavior (HUB-03) has subtle fallback semantics workbox already encodes |
| iOS install/permission state detection | New detection logic | Existing `useInstallBanner` helpers (`detectIOS`, `detectStandalone`) | Already battle-tested in Phase 26 |

**Key insight:** every hand-rollable piece of this phase (push crypto, SW caching, badge state) has a failure mode that is *silent on iOS* — no console, no error, just no notification. Use the reference libraries and spend the verification budget on the physical-device UAT instead.

## Common Pitfalls

### Pitfall 1: iOS 3-strikes silent-push revocation
**What goes wrong:** Three pushes that don't result in a displayed notification → Safari revokes the subscription; all future pushes 404/410. `[VERIFIED: dev.to/progressier "iOS push subscriptions terminated after 3 notifications" + webkit.org userVisibleOnly policy]`
**Why it happens:** (a) missing `event.waitUntil` — the SW is suspended before `showNotification` resolves, counting as silent; (b) conditional suppression logic in the SW; (c) an exception thrown before `showNotification`.
**How to avoid:** `event.waitUntil` wraps ALL async work (success criterion 2 mandates this); `showNotification` is unconditional in the push handler; badge/IDB work happens inside the same waitUntil chain with try/catch so a badge failure can't skip the notification. D-02 suppression is server-side.
**Warning signs:** pushes suddenly 410 after working; `getSubscription()` returns null on next open (D-19 recovery then silently re-subscribes — which also *masks* the root cause, so log revocation-recovery events loudly).

### Pitfall 2: injectManifest silently drops `workbox.runtimeCaching`
**What goes wrong:** HUB-03's NetworkFirst index.html protection vanishes with no build error — next deploy after that, users are stuck on stale index.html.
**Why it happens:** with `strategies: 'injectManifest'` the plugin's `workbox` option is not consulted; routes must be `registerRoute`d in sw.ts. `[CITED: vite-pwa docs + issue #626]`
**How to avoid:** Pattern 4's sw.ts replicates both routes verbatim. Verification step: build, inspect `dist/sw.js` for `html-cache`/`assets-cache` strings, and after deploy confirm a hard-refresh serves the new index (the "don't verify by bundle-hash polling" memory note applies).
**Warning signs:** `dist/sw.js` is tiny (~precache only); UpdatePrompt never appears after a deploy.

### Pitfall 3: Blocking the event loop on push fan-out (weekly-review-500 class)
**What goes wrong:** pywebpush's synchronous HTTPS calls (up to ~10s each on a bad network) run inline in an async cron → Telegram send times out → cron 500s.
**How to avoid:** every `send_push_to_all` call goes through `loop.run_in_executor`; `webpush(timeout=10)` explicit (CLAUDE.md timeout invariant).
**Warning signs:** cron latency jumps; `TimedOut` from python-telegram-bot; Cloud Run request timeouts on `/cron/*`.

### Pitfall 4: UpdatePrompt breaks after the SW migration
**What goes wrong:** the "New version available → Refresh" flow dies: either the prompt never shows, or Refresh does nothing.
**Why it happens:** generateSW auto-emitted the `SKIP_WAITING` message listener; a custom SW without it leaves the new SW stuck in `waiting` forever after `updateServiceWorker(true)`.
**How to avoid:** the `message → SKIP_WAITING → self.skipWaiting()` listener in sw.ts (Pattern 4 §3). Keep `registerType: 'prompt'` + `injectRegister: false` untouched; `useRegisterSW` in UpdatePrompt.tsx needs zero changes.
**Warning signs:** after a deploy + 60s poll, no banner; or banner shows but the page reloads to the old bundle.

### Pitfall 5: pywebpush mutates `vapid_claims` and misreads key formats
**What goes wrong:** reusing one module-level claims dict across sends → the auto-filled `aud` from the first endpoint poisons sends to other push services (relevant the day desktop subscribes, D-17); private key passed in the wrong format → cryptic VAPID errors.
**How to avoid:** construct a fresh `{"sub": ...}` dict per `webpush()` call; load the PEM string from Secret Manager and pass it directly (pywebpush accepts PEM strings or file paths).
**Warning signs:** 401/403 `VapidPkHashMismatch`-style responses from push services.

### Pitfall 6: Testing expectations vs iOS reality
**What goes wrong:** trying to verify push in Safari-tab dev mode, simulators, or desktop and concluding it's broken (or worse, "works").
**Why it happens:** iOS Push API exists only in the installed standalone PWA over HTTPS; simulators don't support web push.
**How to avoid:** unit-test the SW handlers (vitest, mocked `self`) and the backend sender (pytest, mocked `webpush`); the real gate is D-20's physical-iPhone UAT with the deployed Cloud Run URL. Also remember: SPA/auth paths have NO CI coverage — smoke the deployed URL manually (project memory).
**Warning signs:** "push works on my Mac Chrome but not iPhone" — check installed-standalone status first, then permission state in iOS Settings.

### Pitfall 7: Full pytest suite segfaults (existing, inherited)
**What goes wrong:** `pytest tests/` single-process segfaults (grpc/protobuf GC, Python 3.13).
**How to avoid:** run per-file. New test files (`tests/test_push_sender.py`, `tests/test_push_subscription_store.py`, `tests/test_push_api.py`) run individually; 1153+ baseline must hold.

## Code Examples

### Backend: /api/push routes (session-auth, executor pattern — mirrors existing /api/* style)
```python
# interfaces/web_server.py — register BEFORE the SPA mount (Pitfall 1 of Phase 26)
@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, _email: str = Depends(require_hub_session)) -> JSONResponse:
    body = await request.json()
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint", "")
    keys = sub.get("keys") or {}
    # ASVS V5 input validation — endpoint must be an https push-service URL
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail={"error": "invalid subscription"})
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _get_push_store().upsert, sub, body.get("user_agent", ""))
    return JSONResponse(content={"ok": True})

@app.get("/api/push/vapid-public-key")
async def api_vapid_public_key(_email: str = Depends(require_hub_session)) -> JSONResponse:
    return JSONResponse(content={"key": os.environ["VAPID_PUBLIC_KEY"]})

@app.get("/api/settings")   # + PATCH for the mirror toggle (D-09, Settings page)
async def api_get_settings(_email: str = Depends(require_hub_session)) -> JSONResponse:
    loop = asyncio.get_running_loop()
    settings = await loop.run_in_executor(None, _get_hub_settings_store().get)
    from memory.firestore_db import _jsonsafe_doc
    return JSONResponse(content=_jsonsafe_doc(settings))
```

### Frontend: NAVIGATE message handling (notificationclick → Today, D-12)
```tsx
// App.tsx (or a small hook) — SW → router bridge
useEffect(() => {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'NAVIGATE') navigate(event.data.path ?? '/')
  }
  navigator.serviceWorker?.addEventListener('message', handler)
  return () => navigator.serviceWorker?.removeEventListener('message', handler)
}, [navigate])
```

### Frontend: badge reconciliation (D-18)
```ts
// hooks/useAppBadge.ts — call with unreadCount from useUnread
useEffect(() => {
  if (!('setAppBadge' in navigator)) return
  if (unreadCount > 0) void navigator.setAppBadge(unreadCount)
  else void navigator.clearAppBadge()
  // keep the SW's IDB counter honest for the next closed-app stretch
  navigator.serviceWorker?.controller?.postMessage({ type: 'RESET_BADGE', count: unreadCount })
}, [unreadCount])
```

### Nav placement (D-15 discretion, recommendation)
`/settings` route in App.tsx; `Settings` (gear, lucide `Settings` icon) appended to `NAV_ITEMS` in `Sidebar.tsx:34` and — because BottomTabs has exactly 5 slots (Today/Tasks/Klaus/Habits/Health) — on phone put the gear in a page-header position or as a 6th compact tab; simplest phone answer: a gear icon button in the Today header. Final call is UI discretion, but do NOT displace an existing bottom tab.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| APNS-proprietary Safari Push (push packages, `safari-web-push`) | Standard Web Push (VAPID) in Safari/iOS | Safari 16 (macOS) / iOS 16.4 (2023) | Klaus needs zero Apple developer account — plain VAPID |
| `aesgcm` content encoding | `aes128gcm` (RFC 8188) | pywebpush default for years | Use the default; don't set `content_encoding` |
| generateSW for everything | injectManifest when SW needs push/notificationclick | stable vite-plugin-pwa guidance | The migration this phase performs |
| Classic Web Push only | Declarative Web Push (Safari 18.4+, macOS first) | 2025 | Not adopted this phase — Safari-only, no SW logic (badge counter needs the SW); classic push remains the cross-platform path (D-17) |
| iOS 17.4 EU PWA removal scare | Standalone PWAs work outside EU; iOS 26 defaults Home-Screen sites to web-app mode | 2024–2026 | Israel unaffected (established Phase 26) |

**Deprecated/outdated:** `pinecone-client`-style trap doesn't apply here, but note the PyPI package `webpush` (different, newer project) is NOT `pywebpush` — install the exact name `pywebpush`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | All recommended packages tagged [ASSUMED] because slopcheck couldn't run (install denied); registry age/repo/postinstall checks all clean | Package Legitimacy Audit | Low — decade-old official-org packages; planner gates new installs behind checkpoint:human-verify |
| A2 | Re-`subscribe()` after revocation works without a user gesture when permission is already 'granted' (D-19 silent recovery) | Pattern 8 | Silent recovery would need a one-tap banner instead; verify during device UAT |
| A3 | `client.postMessage({NAVIGATE})` after `client.focus()` reliably routes on iOS; `openWindow('/')` fallback works in installed PWA | Pattern 4 §5 | Tap might land on last-viewed route instead of Today; degrade is cosmetic (D-12 spirit kept via openWindow) — verify on device |
| A4 | Default urgency header is sufficient for prompt APNs delivery; no `Urgency: high` needed | Pattern 5 | Worst case: slightly delayed delivery of time-critical classes; trivially add `headers={"Urgency": "high"}` later |
| A5 | In-process `chat_visible_until` (module var) is safe because Cloud Run runs one instance (matches `_hub_user_id_cache` precedent) | Pattern 7 | Multi-instance scale-out could push while chat visible — a UX blemish, not a correctness bug; Firestore field is the escape hatch |
| A6 | 8–10s visibility window (≈3 poll intervals) correctly balances suppression vs missed pushes | Pattern 7 | Too long → suppressed push after locking the phone; too short → banner while reading chat; tune in UAT |
| A7 | `cacheableResponse {statuses:[0,200]}` parity via workbox defaults (no explicit CacheableResponsePlugin needed for same-origin) | Pattern 4 §2 | Add CacheableResponsePlugin explicitly for byte-parity if plan-checker flags it |
| A8 | Notification body truncation at ~1000 chars keeps encrypted payload under the ~4KB APNs cap | Pattern 5 | Oversized payload → push service 413; truncate harder |

## Open Questions

1. **Does the `_router.py` Telegram-reply path (line 362) push through the same `message_class="chat_reply"` with mirror semantics inverted?**
   - What we know: D-01 says everything pushes; this path already sends Telegram natively (it IS Telegram), so "mirroring" is push-side only here.
   - What's unclear: whether pushing Klaus's Telegram replies to the phone creates double-notification annoyance during the mirror week (Telegram app buzz + Klaus PWA buzz for the same reply Amit just prompted on Telegram).
   - Recommendation: D-10 explicitly wants the double-buzz as the audit mechanism — push these too; the D-02 visibility gate doesn't apply (chat not visible if he's in Telegram). Planner should confirm this reading with a note in the plan; it follows the decisions as written.

2. **Where exactly does the hub-reply mirror send get a `Bot` instance?**
   - What we know: `/internal/process-hub-message` currently has no Telegram dependency; `send_and_inject` takes `bot` as a param; the orchestrator singleton and `_router` own bot instances.
   - Recommendation: have the unified delivery function construct/reuse a module-level `Bot(token)` lazily (python-telegram-bot Bot is cheap and stateless for `send_message`), removing the `bot` param dependency for new callers while keeping the old signature for existing ones.

3. **iOS subscription expiry (`expirationTime`)** — Apple may rotate/expire subscriptions server-side.
   - What we know: D-19's re-validate-on-open + 404/410 cleanup covers rotation regardless of cause.
   - Recommendation: no additional handling; the recovery loop is the design.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | frontend build (sw.ts, vite) | ✓ | v25.9.0 / 11.12.1 | — |
| Python (local dev) | backend + tests | ⚠️ system python3 is **3.14.6** — but project `.venv` is Python 3.13 (per repo; 3.14 segfaults grpc — STATE.md) | 3.13 in .venv | Use `.venv` for all pytest runs; never system 3.14 |
| OpenSSL | VAPID key gen (alternative to py-vapid CLI) | ✓ | 3.6.2 | py-vapid CLI |
| gcloud CLI | Secret Manager secret creation (operator step) | ✓ | SDK 570.0.0 | Console UI |
| pywebpush / py-vapid | push sending | ✗ (not installed) | 2.3.0 / 1.9.4 on PyPI | none — install step in plan (gated per audit) |
| workbox-* direct deps | custom SW imports | ✗ direct (✓ transitive @7.4.1 in lockfile) | 7.4.1 | promote to devDependencies |
| Physical iPhone (iOS ≥16.4) | D-20 UAT | ✓ (Amit's device — external) | — | none; manual UAT item |
| Cloud Run HTTPS origin | push requires secure context + installed PWA | ✓ (live `klaus-agent`) | — | — |

**Missing dependencies with no fallback:** physical-device verification steps are human-UAT by nature (29-HUMAN-UAT.md per D-21).
**Missing dependencies with fallback:** none blocking — all installables.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest (existing `tests/`, fakes in `tests/fakes.py`) — run PER-FILE (full-suite segfault, STATE.md) |
| Framework (frontend) | vitest 3.2.4 + @testing-library/react (existing `frontend/src/**/*.test.tsx`) |
| Config file | none explicit for pytest; `frontend/package.json` `"test": "vitest"` |
| Quick run command | `pytest tests/test_push_sender.py -x -q` / `cd frontend && npx vitest run src/hooks/usePush.test.ts` |
| Full suite command | per-file pytest over new+touched files; `cd frontend && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUSH-01 | `PushSubscriptionStore.upsert/list_all/delete/record_*` (endpoint-hash doc id, `_jsonsafe_doc` reads) | unit | `pytest tests/test_push_subscription_store.py -x` | ❌ Wave 0 |
| PUSH-01 | `POST /api/push/subscribe` validates + upserts; rejects non-https endpoint / missing keys; 401 without session | integration | `pytest tests/test_push_api.py::TestSubscribe -x` | ❌ Wave 0 |
| PUSH-01 | `usePush` re-validation logic (granted+null-sub → resubscribe; denied → banner state) | unit (mocked pushManager) | `cd frontend && npx vitest run src/hooks/usePush.test.ts` | ❌ Wave 0 |
| PUSH-02 | `send_push_to_all`: fan-out, per-class TTL, 404/410 delete, failure_count, fresh claims dict, timeout param passed | unit (mock `webpush`) | `pytest tests/test_push_sender.py -x` | ❌ Wave 0 |
| PUSH-02 | `send_and_inject` order: D-02 gate → push (executor) → mirror gate → inject; existing callers unaffected | unit | `pytest tests/test_scheduled_message.py -x` (extend existing) | ⚠️ extend |
| PUSH-02 | sw.ts push handler always calls showNotification inside waitUntil (incl. badge-failure path) | unit (mocked SW globals) | `cd frontend && npx vitest run src/sw.test.ts` | ❌ Wave 0 |
| PUSH-02 | Push arrives on locked physical iPhone (chat reply + one proactive class) | **manual-only** (D-20 — no automation can exercise APNs+iOS) | 29-HUMAN-UAT.md | ❌ Wave 0 (UAT doc) |
| PUSH-03 | `HubSettingsStore` get/update; mirror flag default ON; `toggle_telegram_mirror` + `get_push_health` tools registered in `_HANDLERS` + brain-direct list | unit | `pytest tests/test_hub_settings_store.py tests/test_tools.py -x -k "mirror or push_health"` | ❌ Wave 0 |
| PUSH-03 | Mirror OFF → no Telegram send, push+inject still run; mirror ON → both | unit | `pytest tests/test_scheduled_message.py -x -k mirror` | ⚠️ extend |
| PUSH-03 | Heartbeat `_check_push_health` signals (failure-streak, no-subscription, severity by mirror state) | unit | `pytest tests/test_heartbeat.py -x -k push` | ⚠️ extend |
| PUSH-04 | Badge reconcile hook: setAppBadge(unread), clearAppBadge at 0, RESET_BADGE postMessage | unit | `cd frontend && npx vitest run src/hooks/useAppBadge.test.ts` | ❌ Wave 0 |
| PUSH-04 | Icon badge visible on iPhone after closed-app push; clears on chat view | **manual-only** (iOS home-screen rendering) | 29-HUMAN-UAT.md | ❌ Wave 0 |
| HUB-03 regression | Built `dist/sw.js` contains html-cache NetworkFirst + assets CacheFirst + SKIP_WAITING listener | smoke (grep build output) | `cd frontend && npm run build && grep -q html-cache dist/sw.js && grep -q SKIP_WAITING dist/sw.js` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the touched file's pytest file (`pytest tests/test_<touched>.py -x -q`) or targeted `npx vitest run <file>`
- **Per wave merge:** all phase-29 test files per-file + `cd frontend && npx vitest run` + `npm run build` (SW smoke grep)
- **Phase gate:** 1153+ baseline holds (per-file), frontend suite green, build smoke green, then D-20 physical UAT before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_push_subscription_store.py` — PUSH-01 store
- [ ] `tests/test_push_api.py` — PUSH-01 routes (model on `tests/test_hub_chat.py` client fixtures)
- [ ] `tests/test_push_sender.py` — PUSH-02 sender (mock `pywebpush.webpush`)
- [ ] `tests/test_hub_settings_store.py` — PUSH-03 flag store
- [ ] `frontend/src/sw.test.ts` — SW handler tests (needs mocked `self`/`registration`; exclude sw.ts itself from the app tsc build if needed)
- [ ] `frontend/src/hooks/usePush.test.ts`, `useAppBadge.test.ts`
- [ ] `29-HUMAN-UAT.md` — D-20 device checklist + D-21 mirror-week tracking items
- [ ] Install: `pywebpush` in requirements.txt; workbox devDeps (gated per Package Legitimacy Audit)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `/api/push/*` + `/api/settings` behind `Depends(require_hub_session)` (existing HUB-01 machinery); NEVER weaken `/cron|/internal|/trigger` OIDC (HUB-04 invariant) |
| V3 Session Management | yes | Existing signed-cookie sessions; no new session surface |
| V4 Access Control | yes | Single-user allowlist already enforced at sign-in; subscription docs carry no per-user ACL need |
| V5 Input Validation | yes | Subscribe body: endpoint must be `https://` push-service URL, keys present, length caps (inline validation matching `api_chat_send` style) |
| V6 Cryptography | yes | Never hand-roll — pywebpush handles RFC 8291/8292; VAPID private key ONLY in Secret Manager (`klaus-vapid-private-key`), never in git/env-file/frontend |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious subscribe → push endpoint injection (server POSTs attacker URL) | Tampering/SSRF-ish | Validate endpoint is https + reasonable host; auth-gated route means only Amit can register anyway |
| VAPID private key leak | Information disclosure | Secret Manager only; loaded lazily; not logged; not in SELF.md manifest generation |
| Notification content leak on lock screen | Information disclosure | Accepted by design (D-12 full text — same exposure as Telegram today); iOS preview settings are the user-side control |
| Push payload spoofing | Spoofing | Impossible without the VAPID private key + subscription keys — encryption is end-to-end to the SW |
| Silent-push background abuse | Elevation | Structurally prevented: always-show-notification design (Pitfall 1) |

## Project Constraints (from CLAUDE.md)

- All GCP/Secret Manager resource names lowercase `klaus-` (uppercase = silent 404) → `klaus-vapid-private-key`.
- Every client carries an explicit timeout → `webpush(timeout=10)`.
- Agent turns / heavy work inside tracked requests; push fan-out inside crons via `run_in_executor` (never block the loop; never Starlette BackgroundTask for turns).
- `load_dotenv(override=True)` in any new entry point.
- Env-driven config: VAPID public key via env/endpoint, not baked constants; `core/self_manifest.py` regenerates SELF.md — new tools (D-13) will appear there automatically on deploy.
- Brain never routed through worker first — the new tools are brain-direct (match `get_self_status` registration in the brain-direct list, `core/tools.py:2679`).
- `OutreachLogStore.append` gated on delivery success (redefined: ≥1 channel succeeded — Pattern 1).
- No features inferring eating time from meal slots (not touched this phase).

## Sources

### Primary (HIGH confidence)
- [vite-pwa-org.netlify.app/guide/inject-manifest](https://vite-pwa-org.netlify.app/guide/inject-manifest) — injectManifest migration recipe, SKIP_WAITING prompt-mode snippet, cleanupOutdatedCaches, tsconfig WebWorker
- [webkit.org/blog/12945 "Meet Web Push"](https://webkit.org/blog/12945/meet-web-push/) — user gesture requirement, userVisibleOnly, subscription revocation on violation
- [webkit.org/blog/14112 "Badging for Home Screen Web Apps"](https://webkit.org/blog/14112/badging-for-home-screen-web-apps/) — setAppBadge/clearAppBadge, SW context, notification-permission dependency, badge ≠ user-visible push
- [github.com/web-push-libs/pywebpush](https://github.com/web-push-libs/pywebpush) — webpush() API, ttl/timeout params, vapid_claims mutation, WebPushException handling
- PyPI JSON API (2026-07-02) — pywebpush 2.3.0, py-vapid 1.9.4; npm registry — workbox 7.4.1, vite-plugin-pwa 1.3.0, idb 8.0.3
- Klaus codebase reads: `core/scheduled_message.py`, `frontend/vite.config.ts`, `frontend/src/components/shared/UpdatePrompt.tsx`, `useUnread.ts`, `ChatWindow.tsx`, `InstallBanner.tsx`/`useInstallBanner.ts`, `interfaces/web_server.py` (/api/chat + /internal/process-hub-message), `interfaces/_router.py:362`, `core/heartbeat.py` (Signal + checkers), `core/tools.py` (get_self_status + _HANDLERS), `memory/firestore_db.py` (store patterns + _jsonsafe_doc), `core/auth_google.py` (SecretManagerTokenStorage)

### Secondary (MEDIUM confidence)
- [dev.to/progressier — iOS push subscriptions terminated after 3 notifications](https://dev.to/progressier/how-to-fix-ios-push-subscriptions-being-terminated-after-3-notifications-39a7) — the 3-strikes number + missing-waitUntil-counts-as-silent (cross-consistent with webkit.org policy statements)
- [webkit.org/blog/16535 "Meet Declarative Web Push"](https://webkit.org/blog/16535/meet-declarative-web-push/) — confirms classic-push penalty framing; declarative alternative context
- [Pushpad — Web Push errors explained](https://pushpad.xyz/blog/web-push-errors-explained-with-http-status-codes) — 404 vs 410 semantics, delete-on-410
- [github.com/vite-pwa/vite-plugin-pwa issue #626](https://github.com/vite-pwa/vite-plugin-pwa/issues/626) — runtimeCaching ignored under injectManifest

### Tertiary (LOW confidence — flagged)
- MagicBell/webscraft 2026 PWA-iOS roundups — iOS 26 home-screen default behavior, EU restriction status (used for context only, no design decision rests on them)

## Metadata

**Confidence breakdown:**
- iOS push mechanics (gesture, installed-only, 3-strikes, waitUntil): HIGH — WebKit official + corroborating field reports
- injectManifest migration recipe: HIGH — official vite-pwa docs + current config read directly
- pywebpush usage + cleanup: HIGH — official README + PyPI verification
- notificationclick navigation on iOS (A3) + gesture-free resubscribe (A2): MEDIUM — spec-consistent but device-behavior-sensitive; covered by D-20 physical UAT
- Badge-count sync design (D-18): MEDIUM — sound architecture, drift semantics accepted; reconcile-on-open self-heals
- Package legitimacy: all [ASSUMED] (slopcheck unavailable) — planner gates new installs

**Research date:** 2026-07-02
**Valid until:** ~2026-08-01 (iOS/Safari push behavior is slow-moving; re-check if an iOS major ships mid-phase)
