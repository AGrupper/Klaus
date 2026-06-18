/**
 * useTaskLists.ts — Optimistic task list CRUD hooks.
 *
 * Mirrors the useChat optimistic-mutation pattern for create, rename, and
 * delete list operations. Inbox is implicit (never in the server response)
 * and must be prepended by the calling component.
 *
 * Query key: ['task-lists'] — single cache entry for all user lists.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchLists,
  createList,
  renameList,
  deleteList,
  type TaskList,
} from '../api/task-lists'

/** Stable query key for the task lists collection. */
export const TASK_LISTS_QUERY_KEY = ['task-lists'] as const

// ---------------------------------------------------------------------------
// useTaskLists — query hook
// ---------------------------------------------------------------------------

/**
 * Fetch all user-created task lists.
 * Inbox is implicit — prepend it in the sidebar rendering component.
 */
export function useTaskLists() {
  return useQuery<TaskList[], Error>({
    queryKey: TASK_LISTS_QUERY_KEY,
    queryFn: fetchLists,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  })
}

// ---------------------------------------------------------------------------
// useCreateList — optimistic create mutation
// ---------------------------------------------------------------------------

export function useCreateList() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (name: string) => createList(name),

    onMutate: async (name: string) => {
      await queryClient.cancelQueries({ queryKey: TASK_LISTS_QUERY_KEY })
      const previous = queryClient.getQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY)

      const optimistic: TaskList = {
        id: `optimistic-${Date.now()}`,
        name,
        updated_at: new Date().toISOString(),
      }

      queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, (old) => [
        ...(old ?? []),
        optimistic,
      ])

      return { previous }
    },

    onError: (_err, _name, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: TASK_LISTS_QUERY_KEY })
    },
  })
}

// ---------------------------------------------------------------------------
// useRenameList — optimistic rename mutation
// ---------------------------------------------------------------------------

export function useRenameList() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameList(id, name),

    onMutate: async ({ id, name }) => {
      await queryClient.cancelQueries({ queryKey: TASK_LISTS_QUERY_KEY })
      const previous = queryClient.getQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY)

      queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, (old) =>
        (old ?? []).map((l) =>
          l.id === id ? { ...l, name, updated_at: new Date().toISOString() } : l,
        ),
      )

      return { previous }
    },

    onError: (_err, _vars, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: TASK_LISTS_QUERY_KEY })
    },
  })
}

// ---------------------------------------------------------------------------
// useDeleteList — optimistic delete mutation
// ---------------------------------------------------------------------------

export function useDeleteList() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => deleteList(id),

    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: TASK_LISTS_QUERY_KEY })
      const previous = queryClient.getQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY)

      queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, (old) =>
        (old ?? []).filter((l) => l.id !== id),
      )

      return { previous }
    },

    onError: (_err, _id, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<TaskList[]>(TASK_LISTS_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: TASK_LISTS_QUERY_KEY })
    },
  })
}
