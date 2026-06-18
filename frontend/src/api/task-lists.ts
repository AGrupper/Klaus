/**
 * task-lists.ts — Klaus Hub task list API client.
 *
 * Backend endpoints (27-02):
 *   POST   /api/task-lists               body { name: string } → TaskList
 *   GET    /api/task-lists               → { lists: TaskList[] }
 *   PATCH  /api/task-lists/{id}          body { name: string } → TaskList
 *   DELETE /api/task-lists/{id}          → { ok: true }
 *
 * Note: Inbox is implicit (list_id='inbox') and is NOT returned by GET /api/task-lists.
 * The UI must always render Inbox as the first/default list client-side.
 */
import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A user-created task list. Inbox is implicit and never appears here. */
export interface TaskList {
  id: string
  name: string
  updated_at: string  // ISO timestamp
}

interface TaskListsResponse {
  lists: TaskList[]
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch all user-created lists.
 * Inbox is implicit — the caller should prepend it when rendering the sidebar.
 */
export async function fetchLists(): Promise<TaskList[]> {
  const data = await apiFetch<TaskListsResponse>('/api/task-lists')
  return data.lists
}

/** Create a new list with the given name. Returns the server-created list. */
export async function createList(name: string): Promise<TaskList> {
  return apiFetch<TaskList>('/api/task-lists', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

/** Rename an existing list. Returns the updated list. */
export async function renameList(id: string, name: string): Promise<TaskList> {
  return apiFetch<TaskList>(`/api/task-lists/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
}

/** Delete a list by id. Tasks in the list are moved to Inbox by the server. */
export async function deleteList(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/task-lists/${id}`, { method: 'DELETE' })
}
