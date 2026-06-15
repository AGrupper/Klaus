---
phase: 26-hub-shell
plan: 09
subsystem: ui
tags: [pwa, ios-install, offline, skeleton, vitest]

requires:
  - phase: 26-hub-shell
    provides: app shell (26-06), SW caching contract + apple-touch-icon (26-01)
provides:
  - InstallBanner + useInstallBanner — iOS Add-to-Home-Screen onboarding (HUB-02 / D-12)
  - OfflineIndicator + useOnline — "Offline — showing cached data" strip
  - reusable Skeleton (HUB-03 frontend half)
  - vitest in-memory localStorage setup (test-setup.ts) — fixes a broken jsdom localStorage env-wide
affects: []

tech-stack:
  added: ["@testing-library/jest-dom", "@testing-library/react", "@testing-library/user-event (dev, via 26-06)"]
  patterns: [iOS install detection (no beforeinstallprompt); localStorage access guarded against Safari private-mode throws]

key-files:
  created:
    - frontend/src/components/shared/InstallBanner.tsx
    - frontend/src/components/shared/OfflineIndicator.tsx
    - frontend/src/components/shared/Skeleton.tsx
    - frontend/src/hooks/useInstallBanner.ts
    - frontend/src/hooks/useOnline.ts
    - frontend/src/components/shared/InstallBanner.test.tsx
    - frontend/src/test-setup.ts
  modified:
    - frontend/src/components/layout/AppShell.tsx
    - frontend/vitest.config.ts

key-decisions:
  - "index.html needed no change — the apple-touch-icon link (HUB-02) already ships from 26-01."
  - "localStorage access in useInstallBanner is wrapped in try/catch — Safari private mode throws on read/write and must never crash the banner render."
  - "jsdom in this Node ships a non-functional localStorage; a vitest setupFile installs a clean in-memory Storage so all specs are deterministic."

patterns-established:
  - "D-06/HUB-03: reusable Skeleton shimmer for in-flight data, distinct from stable 'not ready yet' placeholder text."

requirements-completed: [HUB-02, HUB-03]

duration: ~5min (executor) + inline recovery
completed: 2026-06-15
---

# Phase 26 Plan 09: PWA Polish Summary

**The user-facing degradation + install affordances on top of 26-01's service-worker contract: iOS install onboarding banner, offline indicator, and the reusable in-flight Skeleton — mounted into the shell.**

## Performance
- **Tasks:** 3
- **Completed:** 2026-06-15

## Accomplishments
- `Skeleton` shimmer, `OfflineIndicator` (`useOnline` → "Offline — showing cached data"), and `InstallBanner` (`useInstallBanner` iOS gate: iOS && !standalone && !dismissed), all mounted into `AppShell`.
- `InstallBanner.test.tsx`: 11 vitest cases (install gate logic + online/offline toggle).
- Hardened localStorage access for Safari private mode; fixed the broken jsdom localStorage env for the whole frontend test suite via `test-setup.ts`.

## Task Commits
1. **Task 1: Skeleton + OfflineIndicator + useOnline** — `97bdd34` (feat)
2. **Task 2: InstallBanner + useInstallBanner (+ AppShell mount)** — `c0052d9` (feat)
3. **Task 3: InstallBanner.test.tsx** — `8f3dd6c` (test)
4. **Recovery: localStorage hardening + vitest setup** — `e512a41` (fix)

## Deviations from Plan
### Execution-recovery deviation (not a scope change)
**Executor truncated by session limit after Tasks 1+2 + uncommitted test.** The orchestrator committed the test, then fixed a cross-plan integration failure the post-merge gate caught: jsdom's `localStorage` is non-functional in this Node (`localStorage.getItem/clear is not a function`), which crashed `InstallBanner` renders inside `App.test.tsx` and broke `InstallBanner.test.tsx`. Fixed at the root with a vitest `setupFile` (in-memory localStorage) plus a production guard in `useInstallBanner` (Safari private mode also throws).
**Verification:** `npm test` 42 passed; `tsc + vite build` clean.

## Issues Encountered
The session-limit truncation + the latent jsdom localStorage breakage, both handled above.

## Next Phase Readiness
PWA polish complete; the shell degrades gracefully offline and offers iOS install onboarding.

## Self-Check: PASSED

---
*Phase: 26-hub-shell*
*Completed: 2026-06-15*
