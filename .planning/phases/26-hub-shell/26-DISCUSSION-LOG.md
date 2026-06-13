# Phase 26: Hub Shell - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 26-Hub Shell
**Areas discussed:** Sign-in longevity, Timeline scope & now, Timeline freshness, Early-morning empty states, PWA install onboarding, Chat history model, Sign-out/revoke, Unread badge semantics

---

## Sign-in longevity / Auth model

Amit questioned whether auth was needed at all ("can it be localhost / always signed in? — worried about hackers and people signing into their own accounts"). Explained: the hub is public-internet on Cloud Run (no localhost), the chat is a live command channel into Klaus (Gmail/calendar/spend), the allowlist already rejects anyone else's Google account, and a permanent session delivers the "always signed in" feel with the door still locked.

| Option | Description | Selected |
|--------|-------------|----------|
| Google + permanent session | Allowlist to Amit only; sign in once per device, then effectively always-on | ✓ |
| Shared secret link | Bake a long random secret per device; no allowlist identity, leak-prone | |
| No auth (fully open) | Anyone with URL reads everything + commands Klaus | |

**User's choice:** Google + permanent session
**Notes:** Underlying desire = "feels like it's just mine, always on." Permanent-session + once-per-device sign-in satisfies that while the allowlist keeps everyone else out.

---

## Timeline scope & "now"

| Option | Description | Selected |
|--------|-------------|----------|
| Strict today (midnight–midnight) | Only today; past items still visible | ✓ |
| Rolling next 24h | Now → this time tomorrow | |
| Now → end of day only | Hides earlier-today items | |

| Option | Description | Selected |
|--------|-------------|----------|
| Now-line + past dimmed | Marker between past/upcoming, past de-emphasized, auto-scroll to now | ✓ |
| Now-line, past full-weight | Marker but uniform weight | |
| No marker, just chronological | Plain list | |

**User's choice:** Strict today; now-line marker + past dimmed + auto-scroll to now on open.

---

## Timeline freshness

| Option | Description | Selected |
|--------|-------------|----------|
| Refresh on open + focus | Fetch on open and when app regains focus; no polling | ✓ |
| Periodic auto-refresh | Also re-fetch on a 60–90s timer | |
| Load-once + manual only | Fetch on open, otherwise manual | |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, add pull-to-refresh | Swipe-down force refresh on phone | ✓ |
| No, on-focus is enough | Skip the gesture | |

**User's choice:** Refresh on open + focus, plus pull-to-refresh on phone.

---

## Early-morning empty states

| Option | Description | Selected |
|--------|-------------|----------|
| Hide section until ready | Sections with no data don't render | |
| Placeholder "not ready yet" | Quiet "syncing…/coming after briefing" message | ✓ |
| Skeleton shimmer | Loading bars | |

**User's choice:** "Not ready yet" placeholder.
**Notes:** Distinguished from in-flight skeletons (HUB-03) — placeholders for data that won't exist until later in the day; skeletons for actual network loads.

---

## PWA install onboarding

| Option | Description | Selected |
|--------|-------------|----------|
| One-time dismissible banner | Bottom banner w/ Share→Add steps, remembered after dismiss | ✓ |
| Full onboarding screen | Dedicated first-visit walkthrough | |
| Settings-only instructions | No proactive nudge | |

**User's choice:** One-time dismissible banner.

---

## Chat history model

Amit asked whether to do a ChatGPT/Claude-style "new chat + sidebar of past chats" experience. Explained it conflicts with the one-Klaus / Telegram-shared-history design (CHAT-01) and would fork Klaus's continuous-conversation memory model — recommended a single continuous stream, noted threads as a deferred idea.

| Option | Description | Selected |
|--------|-------------|----------|
| One stream + load-more | Single continuous conversation; recent window + scroll-up | ✓ |
| Today only | Single stream, today's messages only | |
| Defer threads, ship one stream now | Same behavior, explicitly flags threads as future | |

**User's choice:** One stream + load-more (~30–50 recent messages, scroll up for older).
**Notes:** Multi-conversation threads recorded in Deferred Ideas, not dropped.

---

## Sign-out / device revoke

| Option | Description | Selected |
|--------|-------------|----------|
| Simple sign-out in Settings | Clears this device only | |
| Sign-out + revoke-all-devices | Plus server-side invalidate all sessions | ✓ |
| No sign-out at all | Permanent only; rotate secret out-of-band | |

**User's choice:** Sign-out + sign-out-everywhere.
**Notes:** Revoke-all needs a server-side bumpable session-version counter (small Firestore doc/profile field) — not the full Firestore session store (HUBX-02).

---

## Unread badge semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Open Klaus tab | Clears on tab open | |
| Scroll to bottom | Clears when newest message viewed | ✓ |
| App focus anywhere | Clears on any focus | |

| Option | Description | Selected |
|--------|-------------|----------|
| All unseen Klaus messages | Replies + proactive + Telegram-originated | ✓ |
| Proactive only | Self-initiated messages only | |

**User's choice:** Clear on scroll-to-bottom; count all unseen Klaus messages.

---

## Claude's Discretion

- Service-worker caching strategy (network-first index.html; cache-first hashed assets).
- Session cookie mechanics, Google Sign-In flow specifics, session-version storage location.
- Frontend project structure, routing, state/data libraries.
- Optimistic-send + polling implementation details; `/api/today` composition internals.

## Deferred Ideas

- ChatGPT-style multi-conversation threads (conflicts with shared-Telegram-history; v2/HUBX).
- TASK-07 (tasks on rail/timeline) → Phase 27; TIME-06 (habits on timeline) → Phase 28.
- Web Push / Telegram-mirror / OS Badging API → Phase 29.
- Periodic auto-refresh / SSE → only if focus-refresh + polling proves insufficient (HUBX-01).
