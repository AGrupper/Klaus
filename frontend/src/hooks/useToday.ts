/**
 * useToday.ts — TanStack Query hook for /api/today.
 *
 * Refresh policy (D-05 — no timer polling):
 *   - refetchOnMount: true    — always fetch fresh data when the Today view mounts
 *   - refetchOnWindowFocus: true — re-fetch when the user switches back to the tab
 *   - NO refetchInterval      — no timer polling; each focus event triggers one fetch
 *
 * Pull-to-refresh: call useRefreshToday() to get a callback that invalidates
 * the ['today'] query key, triggering a background refetch.
 *
 * The server caches expensive sub-calls (Routes API, Garmin) for 30 minutes,
 * so refetch-on-focus does not exhaust upstream quotas (RESEARCH.md D-05 note).
 *
 * Null values in GarminStats / training / coach_note are D-06 signals:
 * "data not yet available" — NOT fetch errors. The query error path handles
 * real network/API failures. Components should render PlaceholderCard for
 * null fields and Skeleton only while isLoading is true (HUB-03).
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { fetchToday } from '../api/today'
import type { TodayData } from '../api/today'

/** Stable query key for the /api/today data. */
export const TODAY_QUERY_KEY = ['today'] as const

/**
 * Hook: fetches /api/today with refetch-on-mount + refetch-on-focus.
 *
 * Returns all TanStack Query fields: data, isLoading, isError, error, etc.
 */
export function useToday() {
  return useQuery<TodayData, Error>({
    queryKey: TODAY_QUERY_KEY,
    queryFn: fetchToday,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    // D-05: explicitly no timer polling
    // refetchInterval is intentionally omitted (equivalent to false)
    // DO NOT add refetchInterval here — it would poll continuously
  })
}

/**
 * Hook: returns a stable callback for pull-to-refresh.
 *
 * Invalidates the ['today'] query key which triggers a background refetch.
 * Safe to call multiple times; the query deduplicates in-flight requests.
 *
 * Usage in TimelineDay:
 *   const refresh = useRefreshToday()
 *   <div onPointerDown={refresh}>…</div>
 */
export function useRefreshToday(): () => void {
  const queryClient = useQueryClient()
  return useCallback(() => {
    queryClient.invalidateQueries({ queryKey: TODAY_QUERY_KEY })
  }, [queryClient])
}
