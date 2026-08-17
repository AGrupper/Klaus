/**
 * useNotifications — bell feed + unread count + follow-ups for Klaus's corner.
 *
 * The read cursor lives on the account (`bell_last_seen` in settings), not in
 * localStorage: marking everything read on the phone has to clear the dot on
 * the Mac too (Amit's UAT). localStorage is kept only as an offline fallback
 * so the dot behaves sensibly before settings load, and the later of the two
 * always wins.
 */
import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  dismissDelivered,
  fetchFollowups,
  fetchNotifications,
  getLastSeen,
  setLastSeen,
} from '../api/notifications'
import { useSettings, useUpdateSettings } from './useSettings'

export function useNotifications() {
  const query = useQuery({
    queryKey: ['notifications'],
    queryFn: () => fetchNotifications(7),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000, // keep the dot honest while the app sits open
  })
  const items = query.data ?? []

  const settings = useSettings()
  const { save } = useUpdateSettings()

  // Whichever cursor is newer wins: the account's, or this device's fallback.
  const serverCursor = settings.data?.bell_last_seen ?? ''
  const localCursor = getLastSeen()
  const cursor = serverCursor > localCursor ? serverCursor : localCursor
  const unread = items.filter((item) => item.at > cursor).length

  /** Stamp the cursor at the newest item — clears the unread dot everywhere. */
  const markSeen = useCallback(() => {
    if (items.length === 0) return
    const newest = items[0].at
    setLastSeen(newest)          // instant locally, survives offline
    save({ bell_last_seen: newest })  // and syncs to every other device
  }, [items, save])

  /** "Mark all read": clear the dot AND every delivered lock-screen push. */
  const markAllRead = useCallback(() => {
    markSeen()
    dismissDelivered()
  }, [markSeen])

  /** Reading one item clears just its notification (if it pushed at all). */
  const dismissOne = useCallback((tag: string | null) => {
    if (tag) dismissDelivered([tag])
  }, [])

  return { ...query, items, unread, markSeen, markAllRead, dismissOne }
}

export function useFollowups() {
  return useQuery({
    queryKey: ['followups'],
    queryFn: fetchFollowups,
    staleTime: 5 * 60_000,
  })
}
