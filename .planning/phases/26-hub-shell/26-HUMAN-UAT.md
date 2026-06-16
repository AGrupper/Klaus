---
status: partial
phase: 26-hub-shell
source: [26-VERIFICATION.md]
started: 2026-06-15
updated: 2026-06-15
---

## Current Test

[awaiting human testing — requires a physical iPhone and a deployed Cloud Run instance]

## Tests

### 1. iOS PWA install banner (HUB-02 / D-12)
expected: Open the hub in Safari on a physical iPhone (not standalone) signed in as Amit; the "Add Klaus to your home screen" banner appears; follow Share → Add to Home Screen; reopen standalone and confirm the banner no longer shows (dismissal persists).
result: [pending]

### 2. Hub ↔ Telegram shared conversation round-trip (CHAT-01/02)
expected: From the deployed hub, send a chat message to Klaus; receive his reply via polling with the "Klaus is thinking…" indicator; confirm the same user message + reply appear in the Telegram conversation history (one continuous conversation).
result: [pending]

### 3. Responsive layout breakpoints (HUB-05)
expected: On a real phone viewport: bottom tabs with Klaus as the center tab, no sidebar/glance-rail/dock-chat. On a real desktop viewport: sidebar + timeline + glance rail + collapsible docked chat. One layout, switching at the md breakpoint.
result: [pending]

### 4. PWA home-screen icon (HUB-02)
expected: After installing on a physical iOS device, the home-screen icon renders correctly (currently a placeholder PNG — final icon art is a known follow-up).
result: [pending]

### 5. Live traffic-aware leave-by / Get Ready chips (TIME-05)
expected: On the deployed hub with the live Google Routes API, a located calendar event shows a "Leave by HH:MM" chip and a "Get Ready at HH:MM" chip (Get Ready = 45 min before leave-by). Unit-tested with a mocked Routes tool; live API integration is the remaining unknown.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
