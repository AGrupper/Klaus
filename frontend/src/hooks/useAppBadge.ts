/**
 * useAppBadge.ts — Reconcile the installed PWA's icon badge with the true
 * unread count (D-18 / PUSH-04).
 *
 * The SW's push handler increments a counter in IndexedDB and calls
 * `navigator.setAppBadge` while the app is closed (sw.ts). Once the app is
 * open/foregrounded, `useUnread` is the source of truth — this hook
 * overwrites the badge to match it and posts `{type:'RESET_BADGE', count}`
 * to the SW so its IDB counter doesn't drift for the next closed-app
 * stretch. "Clear both badges together" (D-18) falls straight out of this:
 * calling it with unreadCount === 0 (e.g. after `markAllSeen`) clears both.
 *
 * Guarded: no-ops when the Badging API is unavailable (desktop browsers
 * without it, older Safari) — never throws.
 */
import { useEffect } from 'react'

type NavigatorWithBadging = Navigator & {
  setAppBadge?: (count?: number) => Promise<void>
  clearAppBadge?: () => Promise<void>
}

/**
 * Call with the current unread count (e.g. `useUnread(messages.length).unreadCount`).
 * Reconciles the icon badge and the SW's IDB counter on every change.
 */
export function useAppBadge(unreadCount: number): void {
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('setAppBadge' in navigator)) return
    const nav = navigator as NavigatorWithBadging
    try {
      if (unreadCount > 0) {
        void nav.setAppBadge?.(unreadCount)
      } else {
        void nav.clearAppBadge?.()
      }
      // Keep the SW's IDB counter honest for the next closed-app stretch.
      navigator.serviceWorker?.controller?.postMessage({ type: 'RESET_BADGE', count: unreadCount })
    } catch {
      // Defensive: badge API failures must never crash the app (D-18).
    }
  }, [unreadCount])
}
