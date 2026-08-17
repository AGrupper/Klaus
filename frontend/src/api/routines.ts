/**
 * routines.ts — routine groups + per-routine streak flames (Paper Hub).
 *
 * GET   /api/routines                → { routines: Routine[] } (members inlined)
 * POST  /api/routines                → Routine
 * PATCH /api/routines/{id}           → Routine
 * POST  /api/routines/{id}/delete    → detaches members (history preserved)
 *
 * Habit membership is written through the habits API (PATCH routine_id);
 * check-ins keep using POST /api/habits/{id}/checkin.
 */
import { apiFetch } from './client'
import type { Habit } from './habits'

/** A habit as it appears inside a routine's member list. */
export interface RoutineMember extends Habit {
  scheduled_today: boolean
  done_today: boolean
  dose_taken: string | null
}

export interface Routine {
  /** null only for the synthetic "Unassigned" group. */
  id: string | null
  name: string
  emoji: string | null
  order: number
  streak: number
  done_today: boolean
  scheduled_today: number
  completed_today: number
  habits: RoutineMember[]
}

export async function fetchRoutines(): Promise<Routine[]> {
  const data = await apiFetch<{ routines: Routine[] }>('/api/routines')
  return data.routines
}

export interface CreateRoutineInput {
  name: string
  emoji?: string | null
  order?: number
}

export async function createRoutine(input: CreateRoutineInput): Promise<Routine> {
  return apiFetch<Routine>('/api/routines', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function editRoutine(
  id: string,
  input: Partial<CreateRoutineInput>,
): Promise<Routine> {
  return apiFetch<Routine>(`/api/routines/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export async function deleteRoutine(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/routines/${id}/delete`, { method: 'POST' })
}
