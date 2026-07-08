/**
 * useHealth.ts — TanStack Query hooks for GET /api/health/{training,nutrition,sleep}.
 *
 * Refresh policy (per 30-UI-SPEC.md § Range toggle → data fetching):
 *   - staleTime: 5 * 60 * 1000 (5 min) — historical data doesn't change intraday
 *     the way Today's timeline does.
 *   - refetchOnWindowFocus: true — a return-to-tab still picks up newly-synced
 *     cron data (e.g. the nightly Hevy/Garmin/biometric-sync pulls).
 *   - No timer-polling config is set — each focus event triggers at most one fetch.
 *   - No mount-refetch override is set — TanStack's default applies; changing the
 *     range triggers a new queryKey anyway, so an explicit override isn't needed.
 *
 * Query key shape: ['health', <tab>, <range>] — mirrors the useToday() /
 * useTaskSummary() convention so each (sub-tab, range) pair caches independently.
 */

import { useQuery } from '@tanstack/react-query'
import {
  fetchTrainingHistory,
  fetchNutritionDetail,
  fetchSleepRecovery,
} from '../api/health'
import type {
  RangeKey,
  TrainingHistoryData,
  NutritionDetailData,
  SleepRecoveryData,
} from '../api/health'

const HEALTH_STALE_TIME_MS = 5 * 60 * 1000 // 5 min

/** Hook: fetches GET /api/health/training?range=<range>. */
export function useTrainingHistory(range: RangeKey) {
  return useQuery<TrainingHistoryData, Error>({
    queryKey: ['health', 'training', range],
    queryFn: () => fetchTrainingHistory(range),
    staleTime: HEALTH_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  })
}

/** Hook: fetches GET /api/health/nutrition?range=<range>. */
export function useNutritionDetail(range: RangeKey) {
  return useQuery<NutritionDetailData, Error>({
    queryKey: ['health', 'nutrition', range],
    queryFn: () => fetchNutritionDetail(range),
    staleTime: HEALTH_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  })
}

/** Hook: fetches GET /api/health/sleep?range=<range>. */
export function useSleepRecovery(range: RangeKey) {
  return useQuery<SleepRecoveryData, Error>({
    queryKey: ['health', 'sleep', range],
    queryFn: () => fetchSleepRecovery(range),
    staleTime: HEALTH_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  })
}
