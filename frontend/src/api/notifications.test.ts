/**
 * notifications.test.ts — bell read-state semantics.
 *
 * Read state is a per-item set (`bell_read_ids`), not a cursor: the feed is
 * newest-first, so a cursor could only ever mean "everything older is read",
 * which collapses viewport-marking into "mark all read". The legacy
 * `bell_last_seen` cursor survives only as a floor so a week of history does
 * not come back as unread on the first load after the upgrade.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  getReadIds,
  itemKey,
  pruneReadIds,
  setReadIds,
  unreadItems,
  type BellItem,
} from './notifications'

function item(at: string, over: Partial<BellItem> = {}): BellItem {
  return {
    id: at,
    type: 'alert',
    title: 'x',
    body: null,
    at,
    claude_session_url: null,
    routine: null,
    target_date: null,
    push_tag: null,
    ...over,
  }
}

describe('itemKey', () => {
  it('distinguishes two items sharing an id but not a type', () => {
    const a = item('2026-08-17T10:00:00', { id: 'dup', type: 'alert' })
    const b = item('2026-08-17T10:00:00', { id: 'dup', type: 'action' })
    expect(itemKey(a)).not.toBe(itemKey(b))
  })

  it('is stable across refetches of the same item', () => {
    const at = '2026-08-17T10:00:00'
    expect(itemKey(item(at, { id: 'r1' }))).toBe(itemKey(item(at, { id: 'r1' })))
  })
})

describe('unreadItems', () => {
  it('treats everything as unread with an empty read set and no floor', () => {
    const items = [item('2026-08-17T10:00:00'), item('2026-08-16T09:00:00')]
    expect(unreadItems(items, new Set(), '')).toHaveLength(2)
  })

  it('leaves older items unread when only a newer one has been seen', () => {
    const seen = item('2026-08-17T10:00:00')
    const older = item('2026-08-16T09:00:00')
    const unread = unreadItems([seen, older], new Set([itemKey(seen)]), '')
    expect(unread.map((i) => i.at)).toEqual([older.at])
  })

  it('honours the legacy cursor as a floor for items at or before it', () => {
    const items = [
      item('2026-08-17T10:00:00'),
      item('2026-08-16T23:59:59'), // exactly at the floor → read
      item('2026-08-16T09:00:00'),
    ]
    const unread = unreadItems(items, new Set(), '2026-08-16T23:59:59')
    expect(unread.map((i) => i.at)).toEqual(['2026-08-17T10:00:00'])
  })
})

describe('read-id storage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('round-trips read ids through localStorage', () => {
    setReadIds(['alert:a:1', 'review:b:2'])
    expect(getReadIds()).toEqual(['alert:a:1', 'review:b:2'])
  })

  it('returns an empty list when storage holds garbage', () => {
    localStorage.setItem('klaus-bell-read-ids', 'not json')
    expect(getReadIds()).toEqual([])
  })
})

describe('pruneReadIds', () => {
  it('drops ids that have aged out of the feed', () => {
    const live = item('2026-08-17T10:00:00')
    const kept = pruneReadIds([itemKey(live), 'alert:gone:2026-07-01T00:00:00'], [live])
    expect(kept).toEqual([itemKey(live)])
  })
})
