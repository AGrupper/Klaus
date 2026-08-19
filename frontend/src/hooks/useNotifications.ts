/**
 * useNotifications — bell feed + unread count + follow-ups for Klaus's corner.
 *
 * Read state is per-item and lives on the account (`bell_read_ids` in
 * settings), not in localStorage: marking things read on the phone has to
 * clear the dot on the Mac too (Amit's UAT). localStorage mirrors it so the
 * dot behaves before settings load and survives offline; the two are unioned,
 * never chosen between, because either side can be ahead.
 *
 * Per-item rather than a cursor: the bell marks rows read as they scroll into
 * view, and the feed is newest-first, so "everything older than X is read"
 * cannot express "I saw the top three but not the nine below them". See
 * api/notifications.ts.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  dismissDelivered,
  fetchFollowups,
  fetchNotifications,
  getLastSeen,
  getReadIds,
  itemKey,
  pruneReadIds,
  setBadgeCount,
  setReadIds,
  unreadItems,
  type BellItem,
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

  const serverIds = settings.data?.bell_read_ids ?? []
  const [localIds, setLocalIds] = useState<string[]>(getReadIds)

  // Refs so markRead can read current values without being re-created on every
  // render. A scroll burst calls it many times before React re-renders, and a
  // stale closure there is exactly how a lost update happens.
  const itemsRef = useRef<BellItem[]>(items)
  itemsRef.current = items
  const serverIdsRef = useRef<string[]>(serverIds)
  serverIdsRef.current = serverIds
  const localRef = useRef<string[]>(localIds)

  const serverKey = serverIds.join(' ')
  const readIds = useMemo(
    // serverIds is a fresh array every render, so compare it by content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    () => new Set<string>([...serverIdsRef.current, ...localIds]),
    [serverKey, localIds],
  )

  // The legacy cursor, read-only: anything at or before it was already read
  // before this device upgraded to per-item state.
  const legacyFloor = settings.data?.bell_last_seen ?? getLastSeen()

  const unreadList = useMemo(
    () => unreadItems(items, readIds, legacyFloor),
    [items, readIds, legacyFloor],
  )
  const unread = unreadList.length
  const unreadKeys = useMemo(() => unreadList.map(itemKey), [unreadList])

  // Keep the home-screen badge equal to the unread count, so marking things
  // read here clears the number on the icon too.
  useEffect(() => {
    setBadgeCount(unread)
  }, [unread])

  /**
   * Mark items read: locally at once, then account-wide.
   *
   * Writes go through useUpdateSettings' debounce, so a flick that puts eight
   * rows on screen still costs one PATCH carrying the full merged set.
   */
  const markRead = useCallback(
    (toMark: BellItem[]) => {
      const known = new Set<string>([...serverIdsRef.current, ...localRef.current])
      const additions = toMark.map(itemKey).filter((key) => !known.has(key))
      if (additions.length === 0) return

      // Prune ids that have aged out of the feed's window so the settings doc
      // cannot grow without bound.
      const merged = pruneReadIds([...known, ...additions], itemsRef.current)
      localRef.current = merged
      setReadIds(merged)
      setLocalIds(merged)
      save({ bell_read_ids: merged })
    },
    [save],
  )

  /** "Mark all read": clear the dot, the badge, and every delivered push. */
  const markAllRead = useCallback(() => {
    markRead(itemsRef.current)
    dismissDelivered()
    setBadgeCount(0)
  }, [markRead])

  /** Reading one item: mark it read and clear its notification, if it pushed. */
  const dismissOne = useCallback(
    (item: BellItem) => {
      markRead([item])
      if (item.push_tag) dismissDelivered([item.push_tag])
    },
    [markRead],
  )

  return {
    ...query,
    items,
    unread,
    unreadKeys,
    readIds,
    markRead,
    markAllRead,
    dismissOne,
  }
}

export function useFollowups() {
  return useQuery({
    queryKey: ['followups'],
    queryFn: fetchFollowups,
    staleTime: 5 * 60_000,
  })
}
