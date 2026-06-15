---
phase: 26-hub-shell
plan: 07
subsystem: ui
tags: [react, tanstack-query, timeline, today]

requires:
  - phase: 26-hub-shell
    provides: /api/today (26-04), app shell + routes + apiFetch client (26-06)
provides:
  - today API client (frontend/src/api/today.ts) + useToday hook (refetch-on-mount/focus, no timer polling — D-05)
  - Today timeline UI (TimelineDay/TimelineItem/NowLine/TimelineHeader/PlaceholderCard) rendered as the hub home screen
affects: [26-08]

tech-stack:
  added: []
  patterns: [self-fetching route component (TimelineDay drives useToday); D-06 not-ready placeholders distinct from HUB-03 shimmer skeletons]

key-files:
  created:
    - frontend/src/api/today.ts
    - frontend/src/hooks/useToday.ts
    - frontend/src/components/timeline/TimelineDay.tsx
    - frontend/src/components/timeline/TimelineItem.tsx
    - frontend/src/components/timeline/NowLine.tsx
    - frontend/src/components/timeline/TimelineHeader.tsx
    - frontend/src/components/timeline/PlaceholderCard.tsx
    - frontend/src/components/timeline/TimelineDay.test.tsx
  modified:
    - frontend/src/App.tsx

key-decisions:
  - "Freshness via refetch-on-mount + refetch-on-focus + pull-to-refresh (D-05), NOT timer polling."
  - "TodayPage in App.tsx renders <TimelineDay/> — the integration point 26-06 reserved (real content replaces the ComingSoon placeholder)."
  - "Meals render as slot labels with macros, never eating times (TIME-03 / CLAUDE.md invariant)."

patterns-established:
  - "D-06 placeholders (stable text, e.g. 'Coach note coming after your morning briefing.') are visually distinct from in-flight shimmer skeletons."

requirements-completed: [TIME-01, TIME-02, TIME-03, TIME-04, TIME-05, TIME-08]

duration: ~5min (executor) + inline recovery
completed: 2026-06-15
---

# Phase 26 Plan 07: Today Timeline UI Summary

**The hub home screen — today's calendar chronologically with all-day events pinned, a now-line marker, past-item dimming, Garmin/weather header, slot-label meals, training block context, and the glance-rail nutrition totals.**

## Performance
- **Tasks:** 3
- **Completed:** 2026-06-15

## Accomplishments
- `today.ts` types + `useToday` (TanStack Query, refetch-on-mount/focus) + `useRefreshToday`.
- Five timeline components consuming `/api/today` (26-04), rendered inside the 26-06 shell via `TodayPage`.
- Loading → shimmer skeletons; error → role="alert"; data → interleaved chronological events with `NowLine` (auto-scroll), past dimming (D-04), slot-label meals (TIME-03), `Week N of 16` block context (TIME-04), and D-06 placeholders.
- `TimelineDay.test.tsx`: 7 vitest cases (loading/error/all-day pin/slot meal/block context/coach note/D-06 placeholder).

## Task Commits
1. **Task 1: today client + useToday hook** — `996de12` (feat)
2. **Task 2: five timeline components** — `3dde4ac` (feat)
3. **Task 3 + wiring: TimelineDay.test.tsx + TodayPage→TimelineDay + build fixes** — `5718f1b` (feat)

## Deviations from Plan
### Execution-recovery deviation (not a scope change)
**Executor truncated by session limit after Task 1 + uncommitted components.** The orchestrator committed the timeline components, then completed Task 3 inline:
- fixed two truncation artifacts blocking tsc (an unescaped apostrophe in `TimelineDay.tsx`, two unused imports in `NowLine.tsx`/`TimelineItem.tsx`),
- wired `TodayPage → <TimelineDay/>` (the 26-06-reserved integration point; not in 26-07's original file list, but required for the timeline to be the home screen — a justified integration edit), and updated two stale `App.test.tsx` assertions that referenced the old "Today — Coming soon" placeholder (now assert the AppShell nav landmark),
- wrote `TimelineDay.test.tsx`.
**Verification:** frontend `tsc + vite build` passes; `npm test` 42 passed.

## Issues Encountered
None beyond the session-limit truncation handled above.

## Next Phase Readiness
26-08 (chat UI) renders alongside the timeline inside the same shell.

## Self-Check: PASSED

---
*Phase: 26-hub-shell*
*Completed: 2026-06-15*
