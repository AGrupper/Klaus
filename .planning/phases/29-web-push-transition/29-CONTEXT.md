# Phase 29: Web Push & Transition - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Native Web Push for the installed Klaus Hub PWA + the Telegram transition path.
Delivers (PUSH-01..04):

- **Enable & subscription:** an enable-push button (user gesture, iOS requirement)
  inside the installed PWA; VAPID subscriptions stored in a new
  `PushSubscriptionStore` and re-validated on each hub open.
- **Delivery:** Klaus's chat replies AND every proactive message (morning briefing,
  21:30 check-in, weekly review, nightly review, autonomous-tick outreach, Phase-28
  habit nudges) arrive as push notifications on the iPhone when the app is closed —
  `event.waitUntil`-wrapped, verified on the physical device.
- **Telegram mirror:** every send mirrors to Telegram behind a runtime flag, left ON
  for ≥1 week before Amit disables it; this phase ships the *retirement path*, not
  the removal.
- **Icon badge:** the installed PWA icon shows an unread-count badge via the Badging
  API, sharing one counter with the existing in-app unread badge.
- **Supporting surface:** a minimal new Settings page (enable-push + mirror toggle),
  Klaus brain-direct tools for mirror toggle + push health, and push-failure alerting
  wired into the existing heartbeat machinery.

**NOT in this phase:** actual Telegram code removal (future cleanup decision after
the trusted mirror week); hub-native interactive check-in UI (buttons in chat);
health-trend pages (Phase 30). Visual/pixel design of the Settings page, banners,
and badge → UI design discretion (no separate ui-phase flagged for 29).

</domain>

<decisions>
## Implementation Decisions

### Push scope & foreground policy
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

### Telegram mirror & retirement
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

### Notification content & tap behavior
- **D-12:** Title **"Klaus"** + **full message text** (iOS truncates/expands).
  **Tap always opens the Today timeline** (home) — NOT the chat, NOT
  context-dependent deep links; the unread badge guides Amit to chat.
  **Each message is its own notification** — no `tag` replacement; iOS stacks by
  app. **Standard sound/vibration** — Klaus behaves like any messaging app; Amit
  tunes it system-side if needed.

### Klaus's own push awareness
- **D-13:** **Two brain-direct tools:** (a) toggle the Telegram-mirror flag, and
  (b) read push health — subscription present/valid, last successful push, mirror
  state. Amit can execute the retirement decision conversationally ("kill the
  mirror"). Follows the `get_self_status` self-aware pattern.
- **D-14:** **Push-failure alerting is built THIS phase**, wired into the existing
  heartbeat/alert machinery — it self-validates during the mirror week (failures
  visible while Telegram still covers delivery), so retirement is just flipping the
  flag with no follow-up build step.

### Enable UX & badge semantics
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

### Verification & rollout sequencing
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (locked source of truth — with this session's decisions)
- `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` — v5.0 design spec:
  § 2 (Notifications = hybrid transition), § 4 Architecture (`PushSubscriptionStore`;
  `core/scheduled_message.py` gains hub push delivery + Telegram mirror flag;
  polling-while-open / push-when-closed), § 5 Build phase 4, § 6 Verification
  (Phase-4 UAT = autonomous-tick outreach as push with mirror on, run a week).
  Where it conflicts with the decisions above, **the decisions here win** (e.g.,
  mirror covers everything, not just proactive).
- `.planning/REQUIREMENTS.md` — PUSH-01..04 + Out-of-Scope table (Badging API only,
  no favicon libraries).
- `.planning/ROADMAP.md` § Phase 29 — goal + 4 success criteria.

### Delivery path (the backend heart of this phase)
- `core/scheduled_message.py` — `send_and_inject` is the single choke-point every
  proactive cron flows through (Telegram send + conversation inject). Push delivery
  + mirror flag hook in here. Callers: `proactive_alerts`, `morning_briefing`,
  `weekly_training_review`, `training_checkin`, `nightly_review`, `autonomous`,
  `heartbeat`.
- `interfaces/web_server.py` — `/internal/process-hub-message` (hub chat replies —
  currently polling-only, must gain push) + `/api/*` session-auth routes for the
  new subscription/settings endpoints; do not touch OIDC `/cron|/internal|/trigger`
  auth (HUB-04 invariant).
- `core/task_dispatch.py` — Cloud Tasks full-CPU path context for where hub replies
  are produced.
- `core/heartbeat.py` — existing stale-cron/alert machinery that D-14 push-failure
  alerting extends.
- `core/tools.py` — `_HANDLERS` dispatch + brain-direct tool convention for the
  D-13 mirror-toggle + push-health tools (model on `get_self_status`).

### Frontend integration points
- `frontend/vite.config.ts` — vite-plugin-pwa config: `strategies: 'generateSW'`,
  `registerType: 'prompt'`, `injectRegister: false` (UpdatePrompt owns
  registration), NetworkFirst html-cache. Adding a push handler requires moving to
  a custom SW (`injectManifest`) WITHOUT breaking the update-prompt flow or the
  stale-index.html protection (HUB-03).
- `frontend/src/hooks/useUnread.ts` + `frontend/src/components/chat/ChatWindow.tsx`
  (markAllSeen on visibility) + `frontend/src/components/shared/UnreadBadge.tsx` —
  the in-app unread counter the icon badge mirrors (D-18) and the chat-visibility
  signal for D-02 suppression.
- `frontend/src/App.tsx` + `frontend/src/components/layout/{Sidebar,BottomTabs}.tsx`
  — where the new `/settings` route + nav entry lands (D-15).
- Phase-26 install-banner component — pattern for the D-16 first-run enable banner.

### Prior-phase context (patterns to follow)
- `.planning/phases/28-habits-supplements/28-CONTEXT.md` — habit nudges (D-15..D-18
  there) ride the autonomous tick and inherit push delivery; slot-nudge TTL class.
- `.planning/phases/27-tasks/27-CONTEXT.md` — the TickTick migration order
  (verified → remove → cancel) that D-11's retirement path mirrors.
- `.planning/phases/26-hub-shell/26-CONTEXT.md` — session auth, Cloud Tasks chat
  path, polling design, PWA/service-worker decisions this phase extends.

### Project invariants
- `CLAUDE.md` § 6 Invariants — single-worker orchestrator singleton; turns inside
  tracked requests; every LLM/etc. client carries explicit timeouts; lowercase
  `klaus-` naming; `load_dotenv(override=True)`.
- `.planning/STATE.md` § Notes — Asia/Jerusalem; Python 3.11/3.13 (never 3.14);
  test baseline must hold; run pytest per-file (full-suite segfault); weekly-review
  500 incident (never block the event loop in cron sends — push sends included).
- **Deploy-verification gotchas (from memory):** SPA/auth paths have NO CI coverage
  — smoke the deployed URL manually; don't verify deploys by Vite bundle-hash
  polling; inline `display` styles override Tailwind responsive classes.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `send_and_inject` (`core/scheduled_message.py`) — single delivery choke-point;
  add push + mirror once, every proactive cron gets it.
- `useUnread` / `markAllSeen` / `UnreadBadge` (frontend) — ready-made unread
  counter the Badging API mirrors (D-18).
- Phase-26 install banner — template for the enable-push banner (D-16).
- `core/heartbeat.py` alert machinery — extension point for push-failure alerting
  (D-14).
- `get_self_status` tool pattern — template for the push-health tool (D-13).
- Firestore store classes + `_jsonsafe_doc` (`memory/firestore_db.py`) — model
  `PushSubscriptionStore` + the settings/flag doc on these.

### Established Patterns
- `/api/*` = session-cookie auth; `/cron|/internal|/trigger` = OIDC — new
  subscription/settings routes go under `/api/*` without weakening OIDC routes.
- Proactive sends must not block the event loop (weekly-review 500 incident) —
  push fan-out needs the same executor/async care.
- OutreachLog append gated on delivery success (D-10 invariant) — decide how push
  vs mirror success interacts with that gate.
- Service worker: `generateSW` today; update-prompt + NetworkFirst index.html are
  load-bearing (HUB-03) and must survive the move to a custom SW.

### Integration Points
- New `PushSubscriptionStore` + mirror-flag/settings storage in
  `memory/firestore_db.py`.
- Push + mirror logic in `core/scheduled_message.py`; push for hub replies in
  `/internal/process-hub-message`.
- `/api/push/*` (subscribe/validate) + `/api/settings` routes in
  `interfaces/web_server.py`.
- Mirror-toggle + push-health tools in `core/tools.py`.
- Push-failure detection in `core/heartbeat.py`.
- Custom service worker (push + notificationclick + setAppBadge) replacing
  `generateSW`; `/settings` route + Today banner in the frontend.

</code_context>

<specifics>
## Specific Ideas

- **The double-buzz is a feature, not a bug** (D-10): Amit explicitly rejected the
  silent mirror — during the transition week a Telegram buzz WITHOUT a matching
  push is his missing-push detector.
- **Tap lands on Today, not chat** (D-12): he wants the notification tap to open
  the home timeline and let the badge pull him into chat — Klaus-the-app first,
  not conversation-first.
- **Suppression scoped tighter than recommended** (D-02): he chose "push unless the
  chat itself is visible" over app-wide suppression — he'd rather get a banner
  while organizing tasks than miss a reply.
- **Conversational retirement** (D-13): "kill the Telegram mirror" said to Klaus in
  chat should actually flip the flag — the transition lever belongs to Klaus's
  self-aware toolset, not just a settings switch.
- Interactive check-ins stay conversational in the hub (D-05) — he's comfortable
  answering the training check-in in words instead of buttons.

</specifics>

<deferred>
## Deferred Ideas

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

</deferred>

---

*Phase: 29-Web Push & Transition*
*Context gathered: 2026-07-02*
