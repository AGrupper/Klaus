/**
 * useTaskSummary.ts — TanStack Query hook for /api/tasks/summary.
 *
 * Returns {due_today, overdue} counts for the GlanceRail and DueTasksBand.
 * Mirrors the useToday refetch-on-focus pattern (D-05):
 *   - refetchOnMount: true    — always fresh when the component mounts
 *   - refetchOnWindowFocus: true — re-fetch when the user returns to the tab
 *   - NO refetchInterval      — no timer polling (matches useToday discipline)
 *
 * Both GlanceRail and DueTasksBand can call this hook; TanStack Query
 * deduplicates the request via the shared TASK_SUMMARY_QUERY_KEY.
 *
 * Covers TASK-07.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { fetchTaskSummary, type TaskSummary } from '../api/tasks'

/** Stable query key for /api/tasks/summary — shared across all consumers. */
export const TASK_SUMMARY_QUERY_KEY = ['tasks', 'summary'] as const

/**
 * Hook: fetches /api/tasks/summary with refetch-on-mount + refetch-on-focus.
 * No timer polling — each mount or focus event triggers one fetch.
 *
 * Returns the full TanStack Query result: data, isLoading, isError, error.
 */
export function useTaskSummary() {
  return useQuery<TaskSummary, Error>({
    queryKey: TASK_SUMMARY_QUERY_KEY,
    queryFn: fetchTaskSummary,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    // DO NOT add refetchInterval — no timer polling (mirrors useToday D-05)
  })
}

/**
 * Hook: returns a stable callback to manually invalidate the summary cache.
 * Call after completing or deleting a task to trigger a background re-fetch.
 */
export function useRefreshTaskSummary(): () => void {
  const queryClient = useQueryClient()
  return useCallback(() => {
    queryClient.invalidateQueries({ queryKey: TASK_SUMMARY_QUERY_KEY })
  }, [queryClient])
}
