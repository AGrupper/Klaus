/**
 * useTasks.ts — Optimistic task CRUD hooks.
 *
 * Mirrors the useChat optimistic-mutation pattern (onMutate/onError/onSettled)
 * for create, update, and complete operations.
 *
 * Query key: ['tasks', listId] — one cache entry per list (including 'inbox').
 * Mutations invalidate the query on settle to sync with the server.
 *
 * Security note (T-27-TI): task content passed to mutations is plain text;
 * React default escaping applies on render. Never use dangerouslySetInnerHTML
 * on task titles or notes.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchTasks,
  createTask,
  updateTask,
  completeTask,
  type Task,
} from '../api/tasks'

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

/** Stable query key for tasks in a given list. 'inbox' for the inbox. */
export function tasksQueryKey(listId?: string) {
  return ['tasks', listId ?? 'all'] as const
}

// ---------------------------------------------------------------------------
// useTasksList — query hook
// ---------------------------------------------------------------------------

/**
 * Fetch tasks for a given list. Pass 'inbox' for the default inbox;
 * undefined to fetch all tasks.
 */
export function useTasks(listId?: string) {
  return useQuery<Task[], Error>({
    queryKey: tasksQueryKey(listId),
    queryFn: () => fetchTasks(listId),
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    // D-18: no timer polling; list refreshes on focus (pull-to-refresh via invalidate)
  })
}

// ---------------------------------------------------------------------------
// useCreateTask — optimistic create mutation
// ---------------------------------------------------------------------------

/**
 * Optimistically appends the new task to the list cache before the server
 * responds. Rolls back on error; invalidates on settle to sync the real id.
 */
export function useCreateTask(listId?: string) {
  const queryClient = useQueryClient()
  const queryKey = tasksQueryKey(listId)

  return useMutation({
    mutationFn: (input: Parameters<typeof createTask>[0]) => createTask(input),

    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<Task[]>(queryKey)

      // Optimistic task — use a client-side id until the server assigns one
      const optimistic: Task = {
        id: `optimistic-${Date.now()}`,
        title: input.title,
        notes: input.notes ?? null,
        status: 'active',
        due_date: input.due_date ?? null,
        due_time: input.due_time ?? null,
        priority: input.priority ?? 'none',
        list_id: input.list_id ?? listId ?? 'inbox',
        recurrence: input.recurrence ?? null,
        updated_at: new Date().toISOString(),
      }

      queryClient.setQueryData<Task[]>(queryKey, (old) => [
        ...(old ?? []),
        optimistic,
      ])

      return { previous }
    },

    onError: (_err, _input, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Task[]>(queryKey, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })
}

// ---------------------------------------------------------------------------
// useUpdateTask — optimistic patch mutation
// ---------------------------------------------------------------------------

/**
 * Optimistically updates the task in the cache. Rolls back on error.
 */
export function useUpdateTask(listId?: string) {
  const queryClient = useQueryClient()
  const queryKey = tasksQueryKey(listId)

  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof updateTask>[1] }) =>
      updateTask(id, patch),

    onMutate: async ({ id, patch }) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<Task[]>(queryKey)

      queryClient.setQueryData<Task[]>(queryKey, (old) =>
        (old ?? []).map((t) =>
          t.id === id ? { ...t, ...patch, updated_at: new Date().toISOString() } : t,
        ),
      )

      return { previous }
    },

    onError: (_err, _vars, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Task[]>(queryKey, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })
}

// ---------------------------------------------------------------------------
// useCompleteTask — optimistic complete mutation
// ---------------------------------------------------------------------------

/**
 * Optimistically removes the task from the list (status=completing removes
 * it from the active list view). Rolls back on error.
 *
 * The caller is responsible for triggering the undo countdown via undoStore.
 */
export function useCompleteTask(listId?: string) {
  const queryClient = useQueryClient()
  const queryKey = tasksQueryKey(listId)

  return useMutation({
    mutationFn: ({ id, completedOn }: { id: string; completedOn: string }) =>
      completeTask(id, completedOn),

    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<Task[]>(queryKey)

      // Optimistically remove the task from the active list view
      queryClient.setQueryData<Task[]>(queryKey, (old) =>
        (old ?? []).filter((t) => t.id !== id),
      )

      return { previous }
    },

    onError: (_err, _vars, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Task[]>(queryKey, context.previous)
      }
    },

    onSettled: () => {
      // Invalidate both the task list and the summary counts
      queryClient.invalidateQueries({ queryKey })
      queryClient.invalidateQueries({ queryKey: ['tasks', 'summary'] })
    },
  })
}
