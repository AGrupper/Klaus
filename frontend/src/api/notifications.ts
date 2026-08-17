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
