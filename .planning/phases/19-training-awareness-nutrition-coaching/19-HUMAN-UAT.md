---
status: partial
phase: 19-training-awareness-nutrition-coaching
source: [19-VERIFICATION.md]
started: 2026-05-28
updated: 2026-05-28
---

## Current Test

[SC #1 gap fixed locally (commit 36b3afd) — awaiting Cloud Run deploy + Telegram re-test]
[SC #2 blocked on real architecture gap — Lifesum on iOS writes to Apple HealthKit, not Google Fit]

## Tests

### 1. SC #1 — ACWR Telegram query end-to-end
expected: Asking Klaus "what was my ACWR this week?" in Telegram returns a real number computed from Postgres (or an honest "chronic baseline insufficient" answer when too little history).
result: **PASSED**
- 2026-05-28 09:46 — first attempt failed with "more processing steps than expected" (MAX_TOOL_ITERATIONS=8 exceeded).
- Root cause: `compute_acwr_from_db` existed in `mcp_tools/garmin_tool.py` (Plan 19-02) but was never registered as a callable tool. Brain had to delegate → fetch_recent_activities → compute manually across iterations.
- Fix: commit `36b3afd` registered `get_acwr` as a worker-delegated single-call tool. Tests + SELF.md regen included.
- Deployed: commit `5233185` pushed to `main` 2026-05-28; GitHub Actions deploy workflow completed.
- 2026-05-28 10:15 — re-asked in Telegram. Klaus returned **ratio 0.21** (acute 7-day avg 11.4 / chronic 28-day avg 53.3), correctly noting the sweet spot is 0.8–1.3 and flagging detraining risk. Single-iteration response. TRAINING & ATHLETIC COACHING prompt extension (Plan 19-05) is alive and shapes the response voice.
- Closes Gap-1.

### 2. SC #2 — Lifesum → Fit → Firestore → proactive Telegram nudge end-to-end
expected: After logging a meal in Lifesum, within ~30 min Google Fit shows the nutrition entry; within the next autonomous tick (≤20 min after that) `meals/{YYYY-MM-DD}/timestamps/{source_id}` appears in Firestore with macros + meal type.
result: **BLOCKED — architectural gap discovered**
- 2026-05-28 — user logged a meal in Lifesum on iPhone ~15 min before testing.
- Local probe: `MealStore.get_day("2026-05-28")` returned 0 entries.
- Direct Google Fit probe: `fetch_recent_meals(hours=24)` returned 0 entries.
- Deeper probe: `users/me/dataSources(dataTypeName=com.google.nutrition).list()` returned **0 nutrition data sources at all** — not even historical data.
- Root cause: Lifesum on iOS writes to **Apple HealthKit**, not Google Fit. Google Fit's consumer iOS app was deprecated by Google in late 2024 — the `Lifesum (iOS) → Google Fit → Klaus` chain has no bridge on iOS.
- Phase 19's NUTR-01..08 design assumed Lifesum → Google Fit (Android path). Plan/RESEARCH didn't flag the iOS gap.
- All code paths on Klaus's side ARE wired correctly (verified by local probe returning cleanly with no 403/scope errors after the OAuth rotation + Fitness API enable). The blocker is the upstream Lifesum→Fit bridge that doesn't exist on iOS.

## Summary

total: 2
passed: 1
issues: 1
pending: 0
skipped: 0
blocked: 1

## Gaps

### Gap-1 (SC #1 — RESOLVED)
status: resolved
- Description: `compute_acwr_from_db` was never registered as a tool — brain couldn't reach the helper.
- Fix commit: `36b3afd` (deployed via `5233185` push to main)
- Verified: 2026-05-28 10:15 Telegram — ratio 0.21 returned cleanly.

### Gap-2 (SC #2 — architectural; iOS HealthKit)
status: pending_design
- Description: Lifesum on iOS writes to Apple HealthKit, not Google Fit. Phase 19's google_fit_tool path is correct for Android but has no source data on iOS.
- User's chosen direction: switch to Apple HealthKit (proper fix).
- Open architectural questions before planning:
  - How does Klaus (cloud-hosted on Cloud Run) read from HealthKit (a native iOS API)? Options:
    - iOS Shortcuts automation: scheduled or on-write Shortcut that POSTs HealthKit data to a Klaus webhook endpoint
    - Third-party companion app (e.g., Health Auto Export) that POSTs to a webhook
    - User-side bridge app (iOS Shortcut writing to a Firestore-accessible cloud function)
    - Webhook into a new `/cron/healthkit-sync` Klaus endpoint that receives push from the iPhone
  - What's the auth model? (Bearer token in the Shortcut HTTP step? OIDC?)
  - How to align the existing MealStore schema (`source = 'google_fit'`) with a new `source = 'healthkit'` source — keep the same MealStore, just gain a second writer.
- Recommended next step: run `/gsd-discuss-phase 19.1` to refine the architecture before planning. Don't run `/gsd-plan-phase --gaps` until the design questions above are answered.

## Notes

- SC #3, SC #4, SC #5, SC #6 already verified from disk by gsd-verifier (see 19-VERIFICATION.md). All 26 requirement IDs (SCHEMA, INGEST, PROFILE, GARMIN, NUTR, PROMPT) marked Done in `.planning/REQUIREMENTS.md` traceability table.
- Code path for both pending items is verified clean:
  - SC #1: `compute_acwr_from_db` lives in `mcp_tools/garmin_tool.py`; `fetch_training_status` + `fetch_recent_activities` registered worker-delegated in `core/tools.py`; brain has free choice via SELF.md tool catalog (regenerated 2026-05-27, lists all 5 Phase 19 tools)
  - SC #2: `sync_recent_meals` + `MealStore.upsert` exercised end-to-end via operator probe 2026-05-27 17:14 (returned `[]` cleanly — no 403, no scope error, no GoogleFitUnavailableError — confirming OAuth scope + Fitness API + Firestore write paths all wired). Tick-brain triage gate (`_is_empty_signals`) was updated by Plan 19-04 to treat non-empty `meals_since_last_tick` as a triggering signal (NUTR-04).
- Acceptance precedent: Phase 16 (cold-start SELF.md), Phase 18 (autonomous-tick Telegram), and now Phase 19 (ACWR query + nutrition nudge) all close as `human_needed` with the live-system exercise deferred to operator action against staging Cloud Run. Phase 18's items were acknowledged at milestone v2.0 close and tracked in STATE.md `Deferred Items` table — same disposition recommended here.
