/**
 * useNotifications read-state tests.
 *
 * The bell marks rows read as they scroll into view, so markRead fires many
 * times in quick succession during one flick. These tests pin the two things
 * that go wrong when it does: a lost update (row A's key overwritten by row
 * B's write) and a write storm (one PATCH per row).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as notificationsApi from '../api/notifications'
import * as settingsApi from '../api/settings'
import { itemKey, type BellItem } from '../api/notifications'
import { useNotifications } from './useNotifications'

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

function item(at: string, id = at): BellItem {
  return {
    id,
    type: 'alert',
    title: id,
    body: null,
    at,
    claude_session_url: null,
    routine: null,
    target_date: null,
    push_tag: null,
  }
}

const NEWER = item('2026-08-18T10:00:00', 'newer')
const OLDER = item('2026-08-17T09:00:00', 'older')

function settings(readIds: string[] = []): settingsApi.HubSettings {
  return {
    push_enabled_at: null,
    appearance: { accent: '#1C2540', flame: '#B02A2A', font: 'default' },
    home_sections: { leaveby: true, stats: true, corner: true, portfolio: false },
    bell_last_seen: null,
    bell_read_ids: readIds,
  }
}

beforeEach(() => {
  localStorage.clear()
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  vi.spyOn(notificationsApi, 'fetchNotifications').mockResolvedValue([NEWER, OLDER])
  vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue(settings())
  vi.spyOn(settingsApi, 'patchSettings').mockResolvedValue(settings())
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useNotifications', () => {
  it('counts an item unread until its key is in the read set', async () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))

    act(() => result.current.markRead([NEWER]))

    await waitFor(() => expect(result.current.unread).toBe(1))
  })

  it('leaves older items unread when a newer one is marked read', async () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))

    act(() => result.current.markRead([NEWER]))

    await waitFor(() =>
      expect(result.current.unreadKeys).toEqual([itemKey(OLDER)]),
    )
  })

  it('keeps both keys when two rows are marked read in the same tick', async () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))

    // Two IntersectionObserver entries arriving back to back — the second
    // must not clobber the first.
    act(() => {
      result.current.markRead([NEWER])
      result.current.markRead([OLDER])
    })

    await waitFor(() => expect(result.current.unread).toBe(0))
  })

  it('coalesces a scroll burst into a single settings write', async () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))
    const patchSpy = vi.mocked(settingsApi.patchSettings)
    patchSpy.mockClear()

    act(() => {
      result.current.markRead([NEWER])
      result.current.markRead([OLDER])
    })

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    expect(patchSpy.mock.calls[0][0]).toEqual({
      bell_read_ids: [itemKey(NEWER), itemKey(OLDER)],
    })
  })

  it('honours read ids that arrive from the account', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue(
      settings([itemKey(NEWER)]),
    )
    const { result } = renderHook(() => useNotifications(), { wrapper })

    await waitFor(() => expect(result.current.unread).toBe(1))
  })

  it('marks everything read on markAllRead', async () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))

    act(() => result.current.markAllRead())

    await waitFor(() => expect(result.current.unread).toBe(0))
  })

  it('prunes ids that are no longer in the feed before writing', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue(
      settings(['alert:aged-out:2026-07-01T00:00:00']),
    )
    const { result } = renderHook(() => useNotifications(), { wrapper })
    await waitFor(() => expect(result.current.unread).toBe(2))
    const patchSpy = vi.mocked(settingsApi.patchSettings)
    patchSpy.mockClear()

    act(() => result.current.markRead([NEWER]))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    expect(patchSpy.mock.calls[0][0]).toEqual({ bell_read_ids: [itemKey(NEWER)] })
  })
})
