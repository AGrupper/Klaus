/**
 * useRoutines — routine groups with optimistic ring check-ins.
 *
 * Check-ins reuse POST /api/habits/{id}/checkin; the optimistic update flips
 * the member's done_today and recomputes the routine's completed_today so
 * the ring fills instantly. Streak/flame values come from the server on
 * refetch — the flame pop moment (completed == scheduled) is detectable
 * client-side without guessing the streak math.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { checkinHabit } from '../api/habits'
import {
  createRoutine,
  deleteRoutine,
  editRoutine,
  fetchRoutines,
  type Routine,
} from '../api/routines'

export function useRoutines() {
  return useQuery({
    queryKey: ['routines'],
    queryFn: fetchRoutines,
    staleTime: 30_000,
  })
}

function invalidator(queryClient: ReturnType<typeof useQueryClient>) {
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['routines'] })
    void queryClient.invalidateQueries({ queryKey: ['habits'] })
  }
}

export function useCheckinMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ habitId, date, done }: { habitId: string; date: string; done: boolean }) =>
      checkinHabit(habitId, date, done),
    onMutate: async ({ habitId, done }) => {
      await queryClient.cancelQueries({ queryKey: ['routines'] })
      const previous = queryClient.getQueryData<Routine[]>(['routines'])
      if (previous) {
        queryClient.setQueryData<Routine[]>(
          ['routines'],
          previous.map((routine) => {
            if (!routine.habits.some((h) => h.id === habitId)) return routine
            const habits = routine.habits.map((h) =>
              h.id === habitId ? { ...h, done_today: done } : h,
            )
            const completed_today = habits.filter(
              (h) => h.scheduled_today && h.done_today,
            ).length
            return { ...routine, habits, completed_today }
          }),
        )
      }
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(['routines'], context.previous)
    },
    onSettled: invalidator(queryClient),
  })
}

export function useCreateRoutine() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: createRoutine, onSettled: invalidator(queryClient) })
}

export function useEditRoutine() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Parameters<typeof editRoutine>[1] }) =>
      editRoutine(id, input),
    onSettled: invalidator(queryClient),
  })
}

export function useDeleteRoutine() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: deleteRoutine, onSettled: invalidator(queryClient) })
}
