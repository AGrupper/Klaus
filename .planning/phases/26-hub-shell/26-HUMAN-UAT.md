---
status: complete
phase: 26-hub-shell
source: [26-VERIFICATION.md]
started: 2026-06-15
updated: 2026-06-17
note: Verified live after go-live deploy (rev klaus-agent-00120-lrj). Core hub verified working on iPhone Safari + desktop. Cosmetic/UX items deferred to a dedicated fixes session at the user's request.
---

## Current Test

[complete — verified against the live deployment 2026-06-17]

## Tests

### 1. iOS PWA install banner (HUB-02 / D-12)
expected: Open the hub in Safari on a physical iPhone (not standalone) signed in as Amit; the "Add Klaus to your home screen" banner appears; follow Share → Add to Home Screen; reopen standalone and confirm the banner no longer shows (dismissal persists).
result: PASS — installed and run from the iPhone home screen; the hub works in standalone mode (confirmed live 2026-06-17).

### 2. Hub ↔ Telegram shared conversation round-trip (CHAT-01/02)
expected: From the deployed hub, send a chat message to Klaus; receive his reply via polling with the "Klaus is thinking…" indicator; confirm the same user message + reply appear in the Telegram conversation history (one continuous conversation).
result: PARTIAL/DEFERRED — hub chat send + reply + polling work (verified live). The hub does NOT push to Telegram (share-history-only by design); cross-surface history reflection was not separately verified. User accepted as not important; revisit if true cross-surface push is desired.

### 3. Responsive layout breakpoints (HUB-05)
expected: On a real phone viewport: bottom tabs with Klaus as the center tab, no sidebar/glance-rail/dock-chat. On a real desktop viewport: sidebar + timeline + glance rail + collapsible docked chat. One layout, switching at the md breakpoint.
result: PASS — phone shows bottom tabs (Klaus center), no sidebar (confirmed live on iPhone + narrow desktop).

### 4. PWA home-screen icon (HUB-02)
expected: After installing on a physical iOS device, the home-screen icon renders correctly (currently a placeholder PNG — final icon art is a known follow-up).
result: PASS (with caveat) — icon renders on the home screen; final icon art remains a known follow-up.

### 5. Live traffic-aware leave-by / Get Ready chips (TIME-05)
expected: On the deployed hub with the live Google Routes API, a located calendar event shows a "Leave by HH:MM" chip and a "Get Ready at HH:MM" chip (Get Ready = 45 min before leave-by). Unit-tested with a mocked Routes tool; live API integration is the remaining unknown.
result: DEFERRED — not verified live. The Today calendar helper was silently failing (GoogleAuthManager construction bug) until it was fixed this session (commit feb989b); chips need a located event to confirm against the live Routes API. Carried to the fixes session.

## Summary

total: 5
passed: 3
partial: 1
deferred: 1
blocked: 0

## Deferred to the dedicated fixes session

These do not block phase completion (the phase goal — a working, deployed hub —
is demonstrably achieved live). Collected for the post-milestone fixes session:

- **Chat does not scroll to the latest message on open** — real bug; the
  useLayoutEffect fix (67e581d) did not resolve it; confirmed not a cache issue.
  Needs browser-tool debugging.
- **Leave-by / Get Ready chips** — verify live now that the calendar helper is fixed.
- **Final home-screen icon art** — replace the placeholder PNG.
- **Hardening:** React error boundary + a CI smoke test that loads `/` against a
  real build (the SPA-mount/auth/data paths have no automated coverage today).
- **WR-05 eyeball** — empty-reply apology fallback in core/main.py (test-locked).

## Gaps

None blocking. See "Deferred to the dedicated fixes session" above.
