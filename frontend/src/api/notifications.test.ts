/**
 * notifications.test.ts — bell unread cursor semantics (localStorage-backed).
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { countUnread, getLastSeen, setLastSeen, type BellItem } from './notifications'

function item(at: string): BellItem {
  return {
    id: at,
    type: 'alert',
    title: 'x',
    body: null,
    at,
    claude_session_url: null,
    routine: null,
    target_date: null,
  }
}

describe('bell unread cursor', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('counts everything unread with no cursor', () => {
    const items = [item('2026-08-17T10:00:00'), item('2026-08-16T09:00:00')]
    expect(countUnread(items)).toBe(2)
  })

  it('counts only items newer than the cursor', () => {
    setLastSeen('2026-08-16T23:59:59')
    const items = [
      item('2026-08-17T10:00:00'),
      item('2026-08-16T23:59:59'), // exactly at cursor → seen
      item('2026-08-16T09:00:00'),
    ]
    expect(countUnread(items)).toBe(1)
  })

  it('round-trips the cursor through localStorage', () => {
    setLastSeen('2026-08-17T07:12:00')
    expect(getLastSeen()).toBe('2026-08-17T07:12:00')
  })
})
