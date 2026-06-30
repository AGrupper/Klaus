/**
 * habits.ts — Klaus Hub habits & supplements API client.
 *
 * Backend endpoints (28-02):
 *   GET    /api/habits              → { habits: Habit[] }  (enriched per-item)
 *   POST   /api/habits              body CreateHabitInput → Habit
 *   PATCH  /api/habits/{id}         body EditHabitInput → Habit
 *   POST   /api/habits/{id}/checkin body { date, done, dose_taken? } → { ok: true }
 *   GET    /api/habits/{id}/history → HabitHistory
 *   GET    /api/habits/summary      → HabitSummary
 *   POST   /api/habits/{id}/soft-delete  → { ok: true }
 *   POST   /api/habits/{id}/restore      → { ok: true }
 *   POST   /api/habits/{id}/hard-delete  → { ok: true }
 *
 * Security note (T-28-xss): habit name, dose, dose_taken are rendered as
 * plain React text — never via dangerouslySetInnerHTML (enforced in components).
 */
import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type HabitType = 'habit' | 'supplement'
export type HabitSlot = 'Morning' | 'Noon' | 'Evening' | 'Bedtime'
export type GridState = 'done' | 'missed' | 'not-scheduled' | 'pending'

/** One entry in the forward-only schedule revision history (D-19). */
export interface ScheduleRevision {
  effective_from: string        // YYYY-MM-DD plain string
  days: 'daily' | number[]     // "daily" or weekday ints (Mon=0, Sun=6)
}

/** Habit/supplement definition document. */
export interface Habit {
  id: string
  name: string
  type: HabitType
  dose: string | null
  slot: HabitSlot
  schedule_history: ScheduleRevision[]
  status: 'active' | 'completing'
  created_at: string           // ISO timestamp
  // Enriched fields from GET /api/habits (list endpoint only — D-07/TIME-06):
  scheduled_today?: boolean
  done_today?: boolean
  dose_taken?: string | null
  streak?: number
}

/** Single cell in the 365-day contribution grid. */
export interface GridCell {
  date: string      // YYYY-MM-DD
  state: GridState
}

/** Full habit history for the ContributionGrid (HABIT-04). */
export interface HabitHistory {
  streak: number
  grid: GridCell[]
}

/** Summary counts for the GlanceRail and Today timeline (TIME-06). */
export interface HabitSummary {
  pending_today: number
  streak_leaders: Array<{ id: string; name: string; streak: number }>
}

/** Input for creating a new habit or supplement (HABIT-01). */
export interface CreateHabitInput {
  name: string
  type?: HabitType
  dose?: string | null
  slot?: HabitSlot
  days?: 'daily' | number[]
}

/** Input for editing an existing habit. Schedule changes append a revision. */
export interface EditHabitInput {
  name?: string
  type?: HabitType
  dose?: string | null
  slot?: HabitSlot
  days?: 'daily' | number[]
  /** Forward-only schedule gate (D-19): server rejects past effective_from values. */
  effective_from?: string
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** Fetch all active habits, enriched with today's completion state. */
export async function fetchHabits(): Promise<Habit[]> {
  const data = await apiFetch<{ habits: Habit[] }>('/api/habits')
  return data.habits
}

/** Fetch the summary: pending_today + streak_leaders (for GlanceRail / TIME-06). */
export async function fetchHabitSummary(): Promise<HabitSummary> {
  return apiFetch<HabitSummary>('/api/habits/summary')
}

/** Create a new habit or supplement definition. */
export async function createHabit(input: CreateHabitInput): Promise<Habit> {
  return apiFetch<Habit>('/api/habits', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

/** Update habit fields. Schedule changes append a forward-only revision (D-19). */
export async function editHabit(id: string, input: EditHabitInput): Promise<Habit> {
  return apiFetch<Habit>(`/api/habits/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

/**
 * Check off or un-check a habit for a given date.
 * Backfill gate D-11: date must be today or yesterday (enforced server-side).
 */
export async function checkinHabit(
  id: string,
  date: string,
  done: boolean,
  dose_taken?: string | null,
): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/checkin`, {
    method: 'POST',
    body: JSON.stringify({ date, done, dose_taken }),
  })
}

/** Fetch the 365-day four-state history grid + streak for a single habit. */
export async function fetchHabitHistory(id: string): Promise<HabitHistory> {
  return apiFetch<HabitHistory>(`/api/habits/${id}/history`)
}

/**
 * Soft-mark the habit 'completing' (opens the D-20 undo window).
 * Hard-delete is deferred 4s; undo calls restoreHabit().
 */
export async function softDeleteHabit(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/soft-delete`, { method: 'POST' })
}

/** Restore a soft-deleted habit back to 'active' (D-20 undo path). */
export async function restoreHabit(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/restore`, { method: 'POST' })
}

/**
 * Permanently delete a habit. Requires status='completing' (set by soft-delete).
 * Called after the 4-second undo window expires (D-20 hard-delete gate).
 */
export async function hardDeleteHabit(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/hard-delete`, { method: 'POST' })
}
