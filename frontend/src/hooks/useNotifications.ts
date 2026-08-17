/**
 * useNotifications — bell feed + unread count + follow-ups for Klaus's corner.
 *
 * Unread is a localStorage cursor (api/notifications.ts); markSeen() stamps
 * the newest item's timestamp and refreshes the count without a refetch.
 */
import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  countUnread,
  fetchFollowups,
  fetchNotifications,
  setLastSeen,
} from '../api/notifications'

export function useNotifications() {
  const query = useQuery({
    queryKey: ['notifications'],
    queryFn: () => fetchNotifications(7),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000, // keep the dot honest while the app sits open
  })
  const items = query.data ?? []

  // Cursor bump forces a recount after markSeen without refetching.
  const [, setCursorBump] = useState(0)
  const unread = countUnread(items)

  const markSeen = useCallback(() => {
    if (items.length > 0) {
      setLastSeen(items[0].at)
      setCursorBump((n) => n + 1)
    }
  }, [items])

  return { ...query, items, unread, markSeen }
}

export function useFollowups() {
  return useQuery({
    queryKey: ['followups'],
    queryFn: fetchFollowups,
    staleTime: 5 * 60_000,
  })
}
