---
phase: 29-web-push-transition
plan: 09
subsystem: ui
tags: [react, hooks, web-push, vapid, badging-api, vitest, pwa]

# Dependency graph
requires:
  - phase: 29-web-push-transition (plans 06/07)
    provides: "backend /api/push/subscribe + /api/push/vapid-public-key routes, custom SW (sw.ts) with push handler + IDB badge counter + RESET_BADGE message listener"
provides:
  - "usePush() — feature-detect + user-gesture enablePush (VAPID fetch -> pushManager.subscribe -> POST /api/push/subscribe) + revalidate() on mount/visibility (standalone-only) implementing D-19 silent recovery"
  - "useAppBadge(unreadCount) — reconciles navigator.setAppBadge/clearAppBadge with the true unread count and posts RESET_BADGE to the SW controller (D-18)"
affects: [29-10, settings-page, chat-window]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Browser-capability hooks follow useInstallBanner's shape: feature-detect -> try/catch every browser-API access -> small {state, action()} return object"
    - "localStorage-persisted flags (push_was_enabled) drive permission-state banners, mirroring install-banner's dismissed-flag pattern"

key-files:
  created:
    - frontend/src/hooks/usePush.ts
    - frontend/src/hooks/usePush.test.ts
    - frontend/src/hooks/useAppBadge.ts
    - frontend/src/hooks/useAppBadge.test.ts
  modified: []

key-decisions:
  - "urlBase64ToUint8Array typed as Uint8Array<ArrayBuffer> (not the default Uint8Array<ArrayBufferLike>) — TypeScript 6's generic TypedArray lib requires this to satisfy PushManager.subscribe's applicationServerKey BufferSource overload"
  - "revalidate() is gated on detectStandalone() (matching useInstallBanner's isStandalone detection) so it never fires in a regular browser tab per Pattern 8 — only the installed PWA re-validates/silently resubscribes"
  - "Revocation-recovery (granted permission + missing subscription) logs via console.warn per Pitfall 1 so the 3-strikes root cause is never silently masked"

patterns-established:
  - "Silent-recovery hooks: on 'granted but resource missing', log loudly before auto-recovering, so operators can still see when platform-level state is being silently reconstructed"

requirements-completed: [PUSH-01, PUSH-04]

# Metrics
duration: ~25min
completed: 2026-07-04
---

# Phase 29 Plan 09: Push Hooks Summary

**usePush (gesture-driven VAPID subscribe + iOS-safe silent revalidation) and useAppBadge (icon-badge reconciliation with the unread counter), both covered by vitest**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-04
- **Tasks:** 2 completed
- **Files modified:** 4 (all new)

## Accomplishments
- `usePush()` feature-detects the Push API, exposes a real user-gesture `enablePush()` (fetch VAPID key -> `pushManager.subscribe({userVisibleOnly:true, applicationServerKey})` -> `POST /api/push/subscribe`), and an automatic `revalidate()` (mount + `visibilitychange`, standalone-only) that idempotently upserts an existing subscription, silently re-subscribes when permission is granted but the subscription is gone (iOS 3-strikes recovery — logged loudly per Pitfall 1), and surfaces `needsReenable` (denied + previously-enabled) / `neverAsked` (never asked) for the Settings/banner UI in Plan 10.
- `useAppBadge(unreadCount)` reconciles `navigator.setAppBadge`/`clearAppBadge` to the true unread count on every change and posts `{type:'RESET_BADGE', count}` to the SW controller, keeping the SW's IndexedDB counter honest for the next closed-app stretch (D-18) — guarded no-op when the Badging API is unavailable.
- Both hooks ship with vitest coverage (11 tests total) exercising the full acceptance-criteria matrix from the plan.

## Task Commits

Each task was committed atomically:

1. **Task 1: usePush hook (subscribe gesture + revalidate)** - `11fd4a3` (feat)
2. **Task 2: useAppBadge hook (reconcile icon badge with unread)** - `7b7db89` (feat)

**Plan metadata:** committed as part of this SUMMARY.md commit (worktree mode — orchestrator handles STATE.md/ROADMAP.md centrally after merge)

## Files Created/Modified
- `frontend/src/hooks/usePush.ts` - feature-detect + `enablePush()` (gesture subscribe) + `revalidate()` (D-19 three-branch re-validation) + `urlBase64ToUint8Array`
- `frontend/src/hooks/usePush.test.ts` - 7 vitest cases: gesture subscribe + POST, granted+null-sub silent resubscribe, granted+existing idempotent upsert, denied+flag needsReenable, denied without flag stays false, default neverAsked, unsupported fallback
- `frontend/src/hooks/useAppBadge.ts` - `useAppBadge(unreadCount)` effect: set/clear badge + `RESET_BADGE` postMessage to the SW controller
- `frontend/src/hooks/useAppBadge.test.ts` - 4 vitest cases: setAppBadge on >0, clearAppBadge at 0, re-reconcile across renders, no-throw when unsupported

## Decisions Made
- Used the existing `apiFetch` client (`frontend/src/api/client.ts`) directly inside `usePush.ts` rather than adding a new `frontend/src/api/push.ts` module, since the plan's `files_modified` scope was limited to the four hook files and `apiFetch` already handles session-cookie credentials + 401 redirect uniformly.
- `urlBase64ToUint8Array` explicitly typed `Uint8Array<ArrayBuffer>` (see key-decisions) to satisfy TypeScript 6's stricter generic-TypedArray `BufferSource` overload on `PushManager.subscribe` — a type-level fix required for the code to compile at all, not a behavior change (Rule 1).
- `revalidate()` also listens for `visibilitychange` (not just mount) per Pattern 8's "on app mount (or visibilitychange -> visible)" — implemented via a ref-held closure so the mount-only effect always calls the latest revalidate logic without needing to be in the dependency array.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed TypeScript compile error in `urlBase64ToUint8Array`**
- **Found during:** Task 1 (usePush hook) — `npx tsc -b` typecheck after initial implementation
- **Issue:** `new Uint8Array(rawData.length)` inferred as `Uint8Array<ArrayBufferLike>` under this project's TypeScript 6 / DOM lib combination, which doesn't satisfy `PushManager.subscribe`'s `applicationServerKey: BufferSource` overload (`ArrayBufferView<ArrayBuffer>` required, not `ArrayBufferLike`)
- **Fix:** Construct the array from an explicit `new ArrayBuffer(rawData.length)` and annotate the function's return type as `Uint8Array<ArrayBuffer>`
- **Files modified:** `frontend/src/hooks/usePush.ts`
- **Verification:** `npx tsc -b` exits 0; `npx vitest run` still 101/101 green
- **Committed in:** `11fd4a3` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/type-compile fix)
**Impact on plan:** Necessary for the code to compile under the project's TypeScript configuration. No scope creep — no behavior change, no new files beyond the plan's four.

## Issues Encountered
None beyond the TypeScript compile fix documented above. `npm install` was required in `frontend/` (node_modules was absent in this worktree checkout) before any vitest/tsc command would run — a one-time environment bootstrap, not a plan deviation (node_modules is gitignored and not part of the plan's file scope).

## User Setup Required

None - no external service configuration required. (VAPID key generation and Secret Manager setup were handled in earlier plans of this phase.)

## Next Phase Readiness

`usePush` and `useAppBadge` are ready to be wired into the Settings page, the push-enable banner, and `ChatWindow` in Plan 10 (which builds `frontend/src/api/chat.ts` + `useChat.ts` in parallel — no overlap with this plan's files). `usePush`'s `enablePush` must be attached to a real click handler (not called on mount) per the iOS user-gesture requirement — Plan 10 owns that wiring. No blockers.

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-04*

## Self-Check: PASSED

All 4 created files and all 2 task commits (`11fd4a3`, `7b7db89`) verified present on disk / in git log.
