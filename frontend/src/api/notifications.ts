/**
 * notifications.ts — the bell feed + Klaus's pending follow-ups.
 *
 * GET /api/notifications?days=N → { notifications: BellItem[] } newest-first
 * GET /api/followups            → { followups: Followup[] } soonest-first
 *
 * Unread state is client-side: the bell stores a last-seen ISO cursor in
 * localStorage; anything newer counts as unread. The server stays stateless.
 */
import { apiFetch } from './client'

export type BellItemType = 'review' | 'alert' | 'action' | 'system'

export interface BellItem {
  id: string
  type: BellItemType
  title: string
  body: string | null
  at: string
  /** Reviews only — deep link to continue the exact Claude session. */
  claude_session_url: string | null
  routine: 'morning' | 'nightly' | 'weekly' | null
  target_date: string | null
  /** Tag of the push this item was delivered as — used to clear it from the
   *  lock screen once it's read in the app. null when it never pushed. */
  push_tag: string | null
}

export interface Followup {
  id: string
  due_at: string
  note: string
  status: string
  origin: string
}

export async function fetchNotifications(days = 7): Promise<BellItem[]> {
  const data = await apiFetch<{ notifications: BellItem[] }>(
    `/api/notifications?days=${days}`,
  )
  return data.notifications
}

export async function fetchFollowups(): Promise<Followup[]> {
  const data = await apiFetch<{ followups: Followup[] }>('/api/followups')
  return data.followups
}

// ---------------------------------------------------------------------------
// Last-seen cursor (unread dot)
// ---------------------------------------------------------------------------

const LAST_SEEN_KEY = 'klaus-bell-last-seen'

export function getLastSeen(): string {
  try {
    return localStorage.getItem(LAST_SEEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setLastSeen(at: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, at)
  } catch {
    // Private-mode storage failure — the dot just stays on; harmless.
  }
}

export function countUnread(items: BellItem[]): number {
  const lastSeen = getLastSeen()
  return items.filter((item) => item.at > lastSeen).length
}

// ---------------------------------------------------------------------------
// Lock-screen dismissal
// ---------------------------------------------------------------------------

/**
 * Ask the service worker to close delivered notifications.
 *
 * `tags` omitted → close everything (the bell's "Mark all read"); otherwise
 * only the named tags. Silently no-ops where there is no active SW
 * (desktop browser tab, jsdom, non-secure context).
 */
export function dismissDelivered(tags?: string[]): void {
  if (typeof navigator === 'undefined' || !navigator.serviceWorker?.controller) return
  navigator.serviceWorker.controller.postMessage({
    type: 'DISMISS_NOTIFICATIONS',
    ...(tags ? { tags } : {}),
  })
}

/**
 * Set the home-screen badge to `count`.
 *
 * The service worker increments the badge on every push and has always had a
 * RESET_BADGE handler — but nothing ever called it, so the number only ever
 * grew and survived "Mark all read" (Amit's UAT). The Hub now drives the
 * badge from the real unread count.
 */
export function setBadgeCount(count: number): void {
  if (typeof navigator === 'undefined' || !navigator.serviceWorker?.controller) return
  navigator.serviceWorker.controller.postMessage({
    type: 'RESET_BADGE',
    count: Math.max(0, Math.floor(count)),
  })
}
