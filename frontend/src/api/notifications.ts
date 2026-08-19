/**
 * notifications.ts — the bell feed + Klaus's pending follow-ups.
 *
 * GET /api/notifications?days=N → { notifications: BellItem[] } newest-first
 * GET /api/followups            → { followups: Followup[] } soonest-first
 *
 * Unread state is client-side and per-item: the bell keeps a set of read item
 * keys (mirrored to the account as `bell_read_ids`). It is deliberately NOT a
 * cursor — the feed is newest-first, so "everything older than X is read"
 * cannot express "I have seen the three rows on screen but not the nine below
 * them", which is exactly what viewport-marking needs. The pre-existing
 * `bell_last_seen` cursor survives read-only, as a floor. The server stays a
 * dumb projection either way.
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
// Per-item read state (unread dot)
// ---------------------------------------------------------------------------

const LAST_SEEN_KEY = 'klaus-bell-last-seen'
const READ_IDS_KEY = 'klaus-bell-read-ids'

/** Cap the stored set so a long-running install cannot grow it unbounded.
 *  Matches the server-side cap in interfaces/routes/misc.py. */
export const MAX_READ_IDS = 500

/**
 * Stable identity for a bell item.
 *
 * `id` alone is not unique across the feed's three sources — an action and an
 * alert can collide — so the key carries the type and the timestamp too. This
 * is the same composite the sheet already used for its React keys.
 */
export function itemKey(item: BellItem): string {
  return `${item.type}:${item.id}:${item.at}`
}

/**
 * The legacy cursor, read-only.
 *
 * Nothing writes it any more. It is kept so that upgrading does not resurrect
 * a week of already-read history as unread: anything at or before the cursor
 * is read regardless of the read set.
 */
export function getLastSeen(): string {
  try {
    return localStorage.getItem(LAST_SEEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function getReadIds(): string[] {
  try {
    const raw = localStorage.getItem(READ_IDS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
  } catch {
    // Garbage or private-mode failure — treat as "nothing read yet".
    return []
  }
}

export function setReadIds(ids: string[]): void {
  try {
    localStorage.setItem(READ_IDS_KEY, JSON.stringify(ids.slice(-MAX_READ_IDS)))
  } catch {
    // Private-mode storage failure — the dot just stays on; harmless.
  }
}

/** Items still unread: not in the read set, and newer than the legacy floor. */
export function unreadItems(
  items: BellItem[],
  readIds: Set<string>,
  lastSeen: string,
): BellItem[] {
  return items.filter(
    (item) => !readIds.has(itemKey(item)) && !(lastSeen && item.at <= lastSeen),
  )
}

/** Drop read ids for items that have aged out of the feed's window. */
export function pruneReadIds(ids: string[], items: BellItem[]): string[] {
  const live = new Set(items.map(itemKey))
  return ids.filter((id) => live.has(id))
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
