---
status: partial
phase: 29-web-push-transition
source: [29-CONTEXT.md (D-20, D-21), 29-02-PLAN.md]
started: 2026-07-05
updated: 2026-07-05
note: Two sections with different lifecycles. Section 1 (D-20) gates phase close —
  all four checks witnessed on the physical iPhone with the Telegram mirror ON.
  Section 2 (D-21) is post-phase tracking only — the phase does NOT stay open for
  the mirror week; items are carried here the same way Phase 26 carried its
  on-device items in 26-HUMAN-UAT.md.
---

# Phase 29 — Human UAT: Device Verification & Mirror-Week Tracking

## Section 1: D-20 Phase-Close Device Verification

The phase closes only when ALL four checks below are witnessed on the physical
iPhone (installed home-screen PWA, Telegram mirror ON). All Klaus sends share the
`send_and_inject` pipe, so the two witnessed push classes (chat reply + proactive)
prove the pipeline; the mirror week catches stragglers.

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | [x] **Enable-push flow** — from the Settings page or the Today banner, tap enable; iOS permission prompt appears (user gesture); permission granted; a subscription is stored (confirm via `get_push_health` or Firestore `push_subscriptions`) | passed | 2026-07-05: subscription stored (web.push.apple.com endpoint, doc efd08270…) |
| 2 | [ ] **Chat-reply push, app closed** — fully close the installed app (swipe away), send Klaus a message from Telegram or wait for a hub-originated turn to complete, and witness the reply arrive as a push notification on the lock screen | retest | 2026-07-05: FAILED — no push, Telegram only. Root cause GAP-1 (VAPID PEM format, `failure_count: 2` on the subscription). Fixed a32c8ca; a manual send after the fix returned sent:1. Re-witness after deploy. |
| 3 | [ ] **Proactive push, app closed** — with the app fully closed, witness one REAL proactive push arrive: an autonomous tick outreach OR a manually-triggered cron (e.g., morning briefing / nightly review trigger) | retest | 2026-07-05: FAILED — same root cause as check 2 (GAP-1). Re-witness after deploy. |
| 4 | [ ] **Icon unread badge** — after a closed-app push, the installed home-screen icon shows an unread-count badge; opening the app and viewing the chat clears both the in-app counter and the icon badge | retest | 2026-07-05: FAILED — consequence of GAP-1 (no push delivered → SW badge handler never ran). Re-witness after deploy. |

### Phase-close summary

total: 4
passed: 1
pending: 3 (retest after GAP-1 deploy)
blocked: 0

## Section 2: D-21 Post-Phase Mirror-Week Tracking

Tracked items only — the phase does NOT stay open for the calendar week (D-21).
These follow the Phase-26 pattern of carried on-device items: recorded here,
checked off as the week unfolds, and closed with the final mirror-off decision.

| # | Tracked item | Status | Notes |
|---|--------------|--------|-------|
| 1 | [ ] **Mirror flag left ON** — `telegram_mirror_enabled` stays true for the whole observation window; every Klaus send goes to BOTH push and Telegram at full volume (D-08/D-10, no `disable_notification`) | tracking | |
| 2 | [ ] **Daily double-buzz audit** — each day, confirm every Telegram message had a matching push (a lone Telegram buzz = a missed push; investigate via `get_push_health` + heartbeat push signals) | tracking | |
| 3 | [ ] **≥1-week observation window** — at least 7 days of real production use with zero unexplained missing pushes before considering the flip (locked decision: Telegram retirement is gradual, not a hard cutover) | tracking | |
| 4 | [ ] **Mirror-off decision** — after the trusted week, Amit flips the mirror off (Settings toggle or "kill the mirror" via the D-13 brain tool). Telegram stays dormant-but-working (webhook intact; still the photo input channel). Code removal is a separate future cleanup decision (D-11) | tracking | |

### Mirror week log

| Date | Pushes matched Telegram? | Anomalies |
|------|--------------------------|-----------|
| | | |

## Gaps

### GAP-1 — Push sends failed: VAPID key format (RESOLVED, pending re-witness)
status: resolved (code) / retest (device)
found: 2026-07-05 device UAT — checks 2/3/4 failed; subscription showed `failure_count: 2`,
`last_error: "Could not deserialize key data … ASN.1 parsing error: invalid length"`.
Root cause: Secret Manager holds the `vapid --gen` PEM, but pywebpush parses a string
`vapid_private_key` as base64url RAW (PEM only works as a file path). Fix a32c8ca converts
PEM → raw base64url at load (derived applicationServerKey verified equal to the deployed
VAPID_PUBLIC_KEY). Live manual send post-fix: sent:1 failed:0.

### GAP-2 — Chat opens at top of history, not latest message
status: resolved (code) / retest (device)
found: 2026-07-05 device UAT (user report). Root cause: AppShell root used
`minHeight: 100dvh` (not `height`), so the flex chain grew past the viewport and the
message list never became its own scroll region — `scrollHeight === clientHeight`
everywhere, and the initial-scroll guard never fired. Fixed 50598d5 + 9771199:
bounded root height, structural `flex-1 min-h-0 overflow-y-auto` scroll region,
guard removed. Retest: open chat → lands on newest message.

### GAP-3 — Full history rendered; user wants recent window + scroll-up pagination
status: resolved (code) / retest (device)
found: 2026-07-05 device UAT (user report). Fixed 4e308e3 + d3b3b6a:
`GET /api/chat/messages` gained `limit` (default 50) + `before=<seq>` cursor +
`has_more`; polls fetch only the newest 50; scrolling near the top auto-loads the
older page with scroll-position anchoring; merges de-dup by seq; unread badge now
keyed on latest seq (history loads can't create unreads). Retest: open chat →
recent window only; scroll up → "Loading earlier messages…" prepends smoothly.
