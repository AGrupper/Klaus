/**
 * useHabits.ts — Optimistic habit CRUD hooks.
 *
 * Mirrors the useTasks pattern (onMutate/onError/onSettled) for check-off
 * and soft-delete operations.
 *
 * Query key: ['habits'] — single cache entry (habits are not split by list).
 * Mutations invalidate the query on settle to sync with the server.
 *
 * Security note (T-28-xss): habit content passed to mutations is plain text;
 * React default escaping applies on render. Never use dangerouslySetInnerHTML.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchHabits,
  fetchHabitSummary,
  fetchHabitHistory,
  createHabit,
  editHabit,
  checkinHabit,
  softDeleteHabit,
  type Habit,
  type HabitHistory,
  type HabitSummary,
  type CreateHabitInput,
  type EditHabitInput,
} from '../api/habits'

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

/** Stable query key for all active habits. */
export const HABITS_QUERY_KEY = ['habits'] as const

// ---------------------------------------------------------------------------
// useHabits — list query hook
// ---------------------------------------------------------------------------

/** Fetch all active habits enriched with today's completion state. */
export function useHabits() {
  return useQuery<Habit[], Error>({
    queryKey: HABITS_QUERY_KEY,
    queryFn: fetchHabits,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  })
}

// ---------------------------------------------------------------------------
// useHabitHistory — per-habit 365-day grid + streak
// ---------------------------------------------------------------------------

/** Fetch the 365-day four-state history + streak for a single habit (HABIT-04). */
export function useHabitHistory(id: string) {
  return useQuery<HabitHistory, Error>({
    queryKey: ['habits', 'history', id] as const,
    queryFn: () => fetchHabitHistory(id),
    refetchOnMount: true,
    refetchOnWindowFocus: false,
    enabled: Boolean(id),
  })
}

// ---------------------------------------------------------------------------
// useHabitSummary — pending_today + streak_leaders
// ---------------------------------------------------------------------------

/** Fetch the summary counts for the GlanceRail and Today timeline (TIME-06). */
export function useHabitSummary() {
  return useQuery<HabitSummary, Error>({
    queryKey: ['habits', 'summary'] as const,
    queryFn: fetchHabitSummary,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  })
}

// ---------------------------------------------------------------------------
// useCreateHabit — create mutation
// ---------------------------------------------------------------------------

/** Create a new habit or supplement. Invalidates the habits list on settle. */
export function useCreateHabit() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateHabitInput) => createHabit(input),

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
    },
  })
}

// ---------------------------------------------------------------------------
// useEditHabit — update mutation
// ---------------------------------------------------------------------------

/** Update an existing habit. Schedule changes append a forward-only revision. */
export function useEditHabit(id: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: EditHabitInput) => editHabit(id, input),

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
    },
  })
}

// ---------------------------------------------------------------------------
// useCheckOffHabit — optimistic toggle mutation (HABIT-02, D-07)
// ---------------------------------------------------------------------------

interface CheckOffArgs {
  habitId: string
  date: string     // YYYY-MM-DD in Asia/Jerusalem
  done: boolean
  doseTaken?: string | null
}

/**
 * Optimistically flips `done_today` on the cached list, rolls back on error,
 * invalidates on settle to sync with the server (D-07 one-tap toggle).
 */
export function useCheckOffHabit() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ habitId, date, done, doseTaken }: CheckOffArgs) =>
      checkinHabit(habitId, date, done, doseTaken),

    onMutate: async ({ habitId, done }) => {
      await queryClient.cancelQueries({ queryKey: HABITS_QUERY_KEY })
      const prev = queryClient.getQueryData<Habit[]>(HABITS_QUERY_KEY)
      // Optimistic: flip done_today state in the cached list
      queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, (old) =>
        (old ?? []).map((h) => (h.id === habitId ? { ...h, done_today: done } : h)),
      )
      return { prev }
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prev !== undefined) {
        queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, ctx.prev)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
      // WR-04: a check-off changes streak leaders + pending count, so the
      // summary query (GlanceRail / timeline) must also refetch — otherwise it
      // goes stale until the next manual refresh.
      queryClient.invalidateQueries({ queryKey: ['habits', 'summary'] })
    },
  })
}

// ---------------------------------------------------------------------------
// useSoftDeleteHabit — optimistic delete mutation (D-20 soft-mark → undo → hard-delete)
// ---------------------------------------------------------------------------

/**
 * Optimistically removes the habit from the list and soft-marks it 'completing'
 * on the server (D-20). The caller drives the undo countdown via undoStore;
 * the 4s timer then hard-deletes, or undo reverts it.
 */
export function useSoftDeleteHabit() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id }: { id: string }) => softDeleteHabit(id),

    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: HABITS_QUERY_KEY })
      const prev = queryClient.getQueryData<Habit[]>(HABITS_QUERY_KEY)
      queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, (old) =>
        (old ?? []).filter((h) => h.id !== id),
      )
      return { prev }
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prev !== undefined) {
        queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, ctx.prev)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: ['habits', 'summary'] })
    },
  })
}
