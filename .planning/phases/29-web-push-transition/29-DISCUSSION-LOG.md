# Phase 29: Web Push & Transition - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 29-Web Push & Transition
**Areas discussed:** Push scope & foreground policy, Telegram mirror & retirement, Notification content & tap behavior, Enable UX & badge semantics, Settings page scope, Klaus's own push awareness, Verification & rollout sequencing

---

## Push scope & foreground policy

| Option | Description | Selected |
|--------|-------------|----------|
| Everything Klaus sends (Recommended) | Replies + every proactive cron + habit nudges; one consistent channel via send_and_inject | ✓ |
| Proactive only | Only Klaus-initiated messages push; replies rely on polling | |
| Curated subset | Pick specific classes; more per-class plumbing | |

**User's choice:** Everything Klaus sends

| Option | Description | Selected |
|--------|-------------|----------|
| Suppress when visible (Recommended) | App foreground = in-app UI is the notification | ✓ (later refined) |
| Always show | Push fires regardless of app state | |
| You decide | Claude picks per iOS PWA support | |

**User's choice:** Suppress when visible — refined by a follow-up: suppression applies ONLY when the chat view itself is visible (see below).

| Option | Description | Selected |
|--------|-------------|----------|
| iOS Focus handles it (Recommended) | No server-side quiet window; Sleep Focus silences overnight | ✓ |
| Server-side quiet window | Klaus holds pushes during e.g. 23:00–07:00 | |
| Drop nighttime pushes | Quiet-window messages injected but never pushed | |

**User's choice:** iOS Focus handles it

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror now, loud logging later (Recommended) | Mirror is the transition safety net; post-retirement failures log loudly + heartbeat alerting + re-subscribe on open | ✓ |
| Permanent Telegram fallback | Keep the bot forever as automatic fallback | |
| You decide | | |

**User's choice:** Mirror now, loud logging later

| Option | Description | Selected |
|--------|-------------|----------|
| Push as text, respond in chat (Recommended) | Inline-keyboard flows push as plain notifications; answer conversationally in hub chat | ✓ |
| Keep these flows Telegram-only | Blocks full retirement | |
| Build hub-native interactive UI now | Significant new UI scope this phase | |

**User's choice:** Push as text, respond in chat

| Option | Description | Selected |
|--------|-------------|----------|
| Existing judgment is enough (Recommended) | Tick-brain triage + repeat-suppression + CoachingTopicStore dedup gate volume | ✓ |
| Add a daily push cap | Server-side max-N/day with silent overflow | |

**User's choice:** Existing judgment is enough

| Option | Description | Selected |
|--------|-------------|----------|
| Suppress on any visible tab (Recommended) | App visible = no push; tab badge is the signal | |
| Push unless chat is visible | Banner fires while on Today/Tasks | ✓ |
| You decide | | |

**User's choice:** Push unless chat is visible — deliberately noisier than the recommendation; he'd rather get a banner while on another tab than miss a reply.

| Option | Description | Selected |
|--------|-------------|----------|
| Per-class TTL (Recommended) | Time-critical classes expire ~1h; briefings/replies persist; values = Claude's discretion | ✓ |
| Everything delivers, no expiry | | |
| You decide | | |

**User's choice:** Per-class TTL

---

## Telegram mirror & retirement

| Option | Description | Selected |
|--------|-------------|----------|
| Everything mirrors (Recommended) | Every send goes to both channels while the flag is on; Telegram thread stays complete for comparison | ✓ |
| Proactive only (per PUSH-03 letter) | Hub chat replies exist only in the hub | |
| You decide | | |

**User's choice:** Everything mirrors

| Option | Description | Selected |
|--------|-------------|----------|
| Runtime toggle in Firestore (Recommended) | Flip from hub or by telling Klaus; immediate, no deploy | ✓ |
| Env var on Cloud Run | Flipping = redeploy; invisible to Klaus | |
| You decide | | |

**User's choice:** Runtime toggle in Firestore

| Option | Description | Selected |
|--------|-------------|----------|
| Path only, removal later (Recommended) | Phase ships push + mirror + flag; Telegram stays dormant-but-working; removal = future cleanup (mirrors Phase-27 TickTick order) | ✓ |
| Schedule removal in this phase | Leaves the phase un-closeable (week outlives it) | |
| Keep Telegram forever as backup | Contradicts milestone goal | |

**User's choice:** Path only, removal later

| Option | Description | Selected |
|--------|-------------|----------|
| Silent Telegram mirror (Recommended) | disable_notification=True; only push buzzes | |
| Both notify | Full duplicates for the week; a lone Telegram buzz exposes a missing push | ✓ |
| You decide | | |

**User's choice:** Both notify — the double-buzz is his missing-push detector.

---

## Notification content & tap behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Full text, truncated by iOS (Recommended) | Title "Klaus" + message body; matches Telegram today | ✓ |
| Short preview only | First ~100 chars; forces tap-through | |
| Per-class summaries | Crafted titles per class; more plumbing | |

**User's choice:** Full text, truncated by iOS

| Option | Description | Selected |
|--------|-------------|----------|
| Always the chat (Recommended) | Tap → Klaus chat scrolled to latest | |
| Context-dependent | Per-class deep links | |
| Today timeline | Always open on home; badge guides to chat | ✓ |

**User's choice:** Today timeline — app-first, not conversation-first.

| Option | Description | Selected |
|--------|-------------|----------|
| Each message stands alone (Recommended) | No tag replacement; iOS stacks by app | ✓ |
| Newest replaces older | Shared tag; earlier messages vanish | |
| Replace within class only | Per-class tags | |

**User's choice:** Each message stands alone

| Option | Description | Selected |
|--------|-------------|----------|
| Standard notification (Recommended) | Normal banner + sound per iOS settings | ✓ |
| Silent by default | Visible-only; easy to miss nudges | |
| You decide | | |

**User's choice:** Standard notification

---

## Enable UX & badge semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Settings page + first-run banner (Recommended) | New Settings page hosts enable-push + mirror toggle; one-time banner on Today (Phase-26 install-banner pattern) | ✓ |
| Banner only | No settings surface; nowhere to re-enable | |
| Chat header button | Bell icon; mirror toggle still homeless | |

**User's choice:** Settings page + first-run banner

| Option | Description | Selected |
|--------|-------------|----------|
| iPhone-first, store supports many (Recommended) | Multi-subscription store from day one; only iPhone verified this phase | ✓ |
| Strictly iPhone only | Single-subscription model; migration later | |
| Both verified this phase | More UAT surface | |

**User's choice:** iPhone-first, store supports many

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror the in-app unread counter (Recommended) | One source of truth; SW setAppBadge while closed; chat view clears both | ✓ |
| Count undelivered pushes | Two counters that can disagree | |
| Dot, not a number | Presence only | |

**User's choice:** Mirror the in-app unread counter

| Option | Description | Selected |
|--------|-------------|----------|
| Silent re-subscribe, banner if blocked (Recommended) | Permission granted → quiet background re-subscribe; permission revoked → explanatory banner | ✓ |
| Always ask before re-subscribing | More friction for a self-healing situation | |
| You decide | | |

**User's choice:** Silent re-subscribe, banner if blocked

---

## Settings page scope

| Option | Description | Selected |
|--------|-------------|----------|
| Strictly this phase's controls (Recommended) | Enable-push + mirror toggle only; skeleton page | ✓ |
| Add sign-out + basics | Sign-out, version, reinstall link | |
| You decide | | |

**User's choice:** Strictly this phase's controls. Nav placement left to UI discretion.

---

## Klaus's own push awareness

| Option | Description | Selected |
|--------|-------------|----------|
| Toggle + status tools (Recommended) | Brain-direct mirror-toggle + push-health tools; conversational retirement | ✓ |
| Read-only status tool | Flag stays Settings-page-only | |
| No new tools | Push invisible to Klaus | |

**User's choice:** Toggle + status tools

| Option | Description | Selected |
|--------|-------------|----------|
| Build it now (Recommended) | Push-failure heartbeat alerting this phase; self-validates during mirror week | ✓ |
| Defer to retirement | Lighter phase, retirement needs another build step | |
| You decide | | |

**User's choice:** Build it now

---

## Verification & rollout sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Complete on verified push, week tracked in UAT (Recommended) | Phase closes on physical iPhone verification with mirror ON; week + mirror-off decision in 29-HUMAN-UAT.md | ✓ |
| Phase stays open the full week | Blocks Phase 30 on calendar time | |
| Complete on deploy + tests | Riskiest; PUSH-02 requires physical proof | |

**User's choice:** Complete on verified push, week tracked in UAT

| Option | Description | Selected |
|--------|-------------|----------|
| One reply + one proactive (Recommended) | Chat-reply push + one real proactive push + badge; shared pipe proves the rest | ✓ |
| Every class witnessed | Days of calendar time for one code path | |
| You decide | | |

**User's choice:** One reply + one proactive

---

## Claude's Discretion

- `PushSubscriptionStore` shape, VAPID key management, web-push library + 404/410 cleanup
- Service-worker `generateSW` → `injectManifest` migration preserving update-prompt + HUB-03
- Chat-visibility tracking mechanism for foreground suppression
- Exact per-class TTL values + message-class taxonomy
- Unread-count sync mechanics (server ↔ push payload ↔ useUnread)
- Push-failure alert thresholds/wording in heartbeat
- Async/executor handling of push sends in crons (weekly-review-500 class)
- Settings page + banner visuals; Settings nav placement

## Deferred Ideas

- Hub-native interactive check-in UI (tappable log/skip/snooze cards) — future phase
- Actual Telegram code removal (incl. resolving the hub photo-input gap) — after ≥1 trusted mirror week
- Desktop push enablement/verification — post-phase (backend ready)
- Server-side quiet hours / daily push caps — rejected; revisit only if volume becomes a problem
- Settings page growth (sign-out, preferences, version) — later phases
