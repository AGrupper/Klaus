---
phase: 29-web-push-transition
plan: 10
subsystem: frontend-hub-push
tags: [push, settings, navigate-bridge, badge, ui]
requires:
  - 29-08 (usePush + useAppBadge hooks)
  - 29-09 (SW push handler + NAVIGATE + IDB badge counter)
  - 29-06 (GET/PATCH /api/settings)
provides:
  - "/settings route + SettingsPage (enable-push + mirror toggle)"
  - "Today first-run push enable banner + re-enable variant"
  - "SW -> router NAVIGATE bridge (notification tap opens Today)"
  - "ChatWindow icon-badge reconciliation + clear-on-view"
affects:
  - frontend/src/App.tsx
  - frontend/src/components/layout/Sidebar.tsx
  - frontend/src/components/timeline/TimelineHeader.tsx
  - frontend/src/components/chat/ChatWindow.tsx
tech-stack:
  added: []
  patterns:
    - "PushEnableBanner mirrors InstallBanner's fixed-bottom shell + dismiss pattern"
    - "Two independent localStorage dismiss keys (first-run vs re-enable) so dismissing one doesn't suppress the other"
key-files:
  created:
    - frontend/src/components/settings/SettingsPage.tsx
    - frontend/src/components/shared/PushEnableBanner.tsx
    - frontend/src/api/settings.ts
  modified:
    - frontend/src/App.tsx
    - frontend/src/components/layout/Sidebar.tsx
    - frontend/src/components/timeline/TimelineHeader.tsx
    - frontend/src/components/chat/ChatWindow.tsx
    - frontend/src/components/timeline/TimelineDay.test.tsx
decisions:
  - "Today header gear lives in TimelineHeader.tsx (the real Today header), not a new today/TodayPage.tsx file — that path doesn't exist in this codebase (see Deviations)"
  - "markAllSeen wrapped in clearBothBadges() so the icon badge clears the instant chat is viewed, rather than waiting for the next 2.5s poll re-render to pick up useAppBadge's reactive effect"
metrics:
  duration: ~45m
  completed: 2026-07-04
---

# Phase 29 Plan 10: Frontend Push UI Wiring + Device UAT Summary

Wired the user-facing push surface — a Settings page with enable-push + Telegram-mirror toggle, a first-run Today banner, the SW-tap-to-Today NAVIGATE bridge, and ChatWindow icon-badge reconciliation — then reached the D-20 physical-device UAT checkpoint that closes the phase.

## What Was Built

**Task 1 — SettingsPage + `/settings` route + nav entry + Today header gear:**
- `frontend/src/components/settings/SettingsPage.tsx`: a deliberate skeleton (D-15) composing (a) an enable-push section driven by `usePush()` — a real-gesture "Enable push" button when not yet asked/subscribed, an instructional re-enable notice when `needsReenable` (D-19), and a confirmed "Push is enabled" state when `isSubscribed`; (b) a Telegram-mirror checkbox backed by `GET /api/settings` (react-query `useQuery`) and `PATCH /api/settings` (react-query `useMutation`, cache-synced onSuccess).
- `frontend/src/api/settings.ts`: new thin client (`fetchSettings`/`patchSettings`) following the existing `api/habits.ts` pattern.
- `App.tsx`: added `<Route path="/settings" element={<SettingsPage />} />`.
- `Sidebar.tsx`: appended `{ label: 'Settings', path: '/settings', icon: Settings }` to `NAV_ITEMS` (desktop nav).
- `TimelineHeader.tsx`: added a phone-only gear button (`className="md:hidden"`, Tailwind — never inline `display`, per the responsive-display gotcha) in the date-heading row that navigates to `/settings`. BottomTabs was left untouched (its 5 slots are full, per the plan's explicit instruction).

**Task 2 — PushEnableBanner + NAVIGATE bridge + ChatWindow badge clear:**
- `frontend/src/components/shared/PushEnableBanner.tsx`: new fixed-bottom banner modeled directly on `InstallBanner.tsx`'s shell (z-40, safe-area padding, 44px dismiss target). Gated on Push API support, standalone mode, and either `usePush().neverAsked` (first-run, D-16, shows the "Enable push" CTA wired to `enablePush`) or `usePush().needsReenable` (D-19, instructional-only — no functional button since `Notification.permission` is already `'denied'` there). Two independent localStorage dismiss keys keep the two lifecycle moments from suppressing each other. Mounted on `TodayPage` (the `App.tsx` wrapper around `TimelineDay`).
- `App.tsx`: added the SW → router bridge — a `navigator.serviceWorker` `'message'` listener (guarded, feature-detected) that calls `navigate(event.data.path ?? '/')` on `{type:'NAVIGATE'}`, matching `sw.ts`'s `notificationclick` handler which always posts `path: '/'` (D-12: tap opens Today, never chat).
- `ChatWindow.tsx`: added `useAppBadge(unreadCount)` alongside the existing `useUnread(allMessages.length)` so the icon badge stays reconciled to the true unread count. Wrapped `markAllSeen` in a new `clearBothBadges()` callback that also calls `navigator.clearAppBadge()` and posts `{type:'RESET_BADGE', count:0}` directly — this clears the icon badge the instant the last message becomes visible (IntersectionObserver), rather than depending on the next 2.5s poll cycle to re-render with a lowered `unreadCount`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking/file-location] Plan's `frontend/src/components/today/TodayPage.tsx` doesn't exist in this codebase**
- **Found during:** Task 1 read_first (App.tsx / project scan)
- **Issue:** The plan's file list names `frontend/src/components/today/TodayPage.tsx` as the Today page to modify for the header gear. In the actual codebase (post Phase 26/27/28), the `/` route renders an inline `TodayPage()` wrapper function defined in `App.tsx`, which composes the real `frontend/src/components/timeline/TimelineDay.tsx` — and the actual visual header (date heading, Garmin stats, weather) lives in `frontend/src/components/timeline/TimelineHeader.tsx`, not a `today/` directory.
- **Fix:** Added the gear button directly to `TimelineHeader.tsx`'s date-heading row (the true "Today header" the plan's RESEARCH.md note refers to), and mounted `PushEnableBanner` inside `App.tsx`'s inline `TodayPage()` wrapper. No `today/` directory was created — it would have duplicated `TimelineDay`/`TimelineHeader` for no functional benefit.
- **Files modified:** `frontend/src/components/timeline/TimelineHeader.tsx`, `frontend/src/App.tsx`
- **Commits:** `3f317ba`, `036b9dc`

**2. [Rule 1 - Bug] `TimelineHeader`'s new `useNavigate()` call broke `TimelineDay.test.tsx`**
- **Found during:** Task 1 verification (`npx vitest run`)
- **Issue:** Adding the gear button's `useNavigate()` call to `TimelineHeader.tsx` requires a Router context. `TimelineDay.test.tsx` rendered `<TimelineDay />` directly (no `MemoryRouter`) in 8 test cases, which would throw "useNavigate() may be used only in the context of a `<Router>` component."
- **Fix:** Added a `renderTimelineDay()` helper wrapping every render call in `<MemoryRouter>`, and replaced all 8 call sites (including the `expect(() => ...).not.toThrow()` case).
- **Files modified:** `frontend/src/components/timeline/TimelineDay.test.tsx`
- **Commit:** `3f317ba`

## Known Stubs

None. Both new UI surfaces (SettingsPage, PushEnableBanner) are wired to real hooks (`usePush`, `useAppBadge`) and real endpoints (`GET`/`PATCH /api/settings`) — no hardcoded empty values or placeholder copy shipped to production paths.

## Verification

- `cd frontend && npx vitest run` — 17 test files, 103 tests, all green (0 regressions)
- `cd frontend && npx tsc --noEmit -p tsconfig.app.json` — exits 0
- `cd frontend && npm run build` — exits 0 (Vite build + injectManifest SW build both succeed)
- `grep -q "/settings" src/App.tsx`, `grep -q "Settings" src/components/layout/Sidebar.tsx`, `grep -q "NAVIGATE" src/App.tsx`, `grep -q "clearAppBadge" src/components/chat/ChatWindow.tsx`, `grep -q "enablePush" src/components/shared/PushEnableBanner.tsx` — all pass

## Self-Check

- FOUND: frontend/src/components/settings/SettingsPage.tsx
- FOUND: frontend/src/components/shared/PushEnableBanner.tsx
- FOUND: frontend/src/api/settings.ts
- Commit 3f317ba: FOUND
- Commit 036b9dc: FOUND

## Self-Check: PASSED

## Phase Close — D-20 Device UAT

All implementation tasks (1-2) are committed and verified. Task 3 is a `checkpoint:human-verify` (gate="blocking") for the D-20 physical-iPhone push verification — automation cannot exercise APNs + iOS notification rendering. This SUMMARY documents the implementation; the checkpoint below is returned to the orchestrator for the human to run against the deployed Cloud Run URL in the installed home-screen PWA.

The Section 1 checklist in `.planning/phases/29-web-push-transition/29-HUMAN-UAT.md` (created in Plan 02) is the record of truth for this verification — it is not yet filled in (all 4 items still `pending`).
