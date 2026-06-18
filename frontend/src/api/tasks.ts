/**
 * tasks.ts — Klaus Hub task API client.
 *
 * Backend endpoints (27-02):
 *   POST   /api/tasks                    body { title, notes?, due_date?, due_time?, priority?, list_id?, recurrence? } → Task
 *   GET    /api/tasks?list_id=…          → { tasks: Task[] }
 *   GET    /api/tasks/summary            → TaskSummary { due_today, overdue }
 *   PATCH  /api/tasks/{id}               body partial Task → Task
 *   POST   /api/tasks/{id}/complete      body { completed_on: string } → { next_id: string | null }
 *   POST   /api/tasks/{id}/undo          → { ok: true }
 *   POST   /api/tasks/{id}/hard-delete   → { ok: true }
 *
 * Security note (T-27-TI): task content is plain text; React default escaping
 * applies on render. dangerouslySetInnerHTML must never be used on task titles
 * or notes (enforced in 27-05 components).
 */
import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Priority = 'none' | 'low' | 'medium' | 'high'
export type TaskStatus = 'active' | 'completing'

/** Recurrence rule shape matching TaskStore (27-01). */
export interface RecurrenceRule {
  cadence: 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'every_n_days'
  every_n?: number
  anchor: 'schedule' | 'completion'
}

/** Task document shape returned by all task endpoints. */
export interface Task {
  id: string
  title: string
  notes: string | null
  status: TaskStatus
  due_date: string | null   // YYYY-MM-DD (plain string — T-27-IV)
  due_time: string | null   // HH:MM (24h)
  priority: Priority
  list_id: string            // 'inbox' or a user-created list id
  recurrence: RecurrenceRule | null
  updated_at: string         // ISO timestamp
}

/** Summary counts for the glance rail and Today timeline (TASK-07). */
export interface TaskSummary {
  due_today: number
  overdue: number
}

interface TasksResponse {
  tasks: Task[]
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch tasks, optionally filtered by list.
 * Pass `listId = 'inbox'` for Inbox; omit for all tasks.
 */
export async function fetchTasks(listId?: string): Promise<Task[]> {
  const path = listId ? `/api/tasks?list_id=${encodeURIComponent(listId)}` : '/api/tasks'
  const data = await apiFetch<TasksResponse>(path)
  return data.tasks
}

/**
 * Fetch the count summary: due today + overdue.
 * Used by the glance rail and the DueTasksBand (TASK-07).
 */
export async function fetchTaskSummary(): Promise<TaskSummary> {
  return apiFetch<TaskSummary>('/api/tasks/summary')
}

/** Create a new task. Returns the server-assigned task. */
export async function createTask(input: {
  title: string
  notes?: string
  due_date?: string | null
  due_time?: string | null
  priority?: Priority
  list_id?: string
  recurrence?: RecurrenceRule | null
}): Promise<Task> {
  return apiFetch<Task>('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

/** Update task fields. Pass only the fields that changed. */
export async function updateTask(
  id: string,
  patch: Partial<Pick<Task, 'title' | 'notes' | 'due_date' | 'due_time' | 'priority' | 'list_id' | 'recurrence'>>,
): Promise<Task> {
  return apiFetch<Task>(`/api/tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

/**
 * Mark a task complete. For recurring tasks the server generates the next
 * instance and returns its id (next_id). For non-recurring tasks next_id is null.
 *
 * @param completedOn - YYYY-MM-DD in Asia/Jerusalem (client provides the local date)
 */
export async function completeTask(
  id: string,
  completedOn: string,
): Promise<{ next_id: string | null }> {
  return apiFetch<{ next_id: string | null }>(`/api/tasks/${id}/complete`, {
    method: 'POST',
    body: JSON.stringify({ completed_on: completedOn }),
  })
}

/**
 * Undo a completed task (reverses the status=completing state on the server).
 * Called within the 4-second undo window before hard-delete fires.
 */
export async function undoTask(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/tasks/${id}/undo`, { method: 'POST' })
}

/**
 * Permanently delete a task. Called after the 4-second undo window expires,
 * or when the user explicitly deletes (bypassing undo).
 * The route also handles undoing the next-instance when undoing a recurrence completion.
 */
export async function hardDeleteTask(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/tasks/${id}/hard-delete`, { method: 'POST' })
}
