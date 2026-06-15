/**
 * today.ts — Type contract + fetch function for /api/today.
 *
 * The /api/today endpoint (26-04) composes a full-day snapshot:
 *   - Calendar events: all-day pinned + timed sorted chronologically (TIME-01)
 *   - Garmin morning stats: sleep, HRV, body battery, resting HR (TIME-02)
 *   - Weather: one-line summary (TIME-02)
 *   - Meals: slot labels + macros — never eating-time framing (TIME-03)
 *   - Training: item + block context "Week N of 16" (TIME-04)
 *   - Leave-by/Get Ready chips: populated when a timed event has a location (TIME-05)
 *   - Coach note: one-liner from morning briefing, or null (D-06 placeholder)
 *   - Nutrition totals: running day totals for glance rail (TIME-08)
 *
 * Null values for garmin/training/coach_note signal D-06 "not yet available"
 * states, NOT fetch errors. Fetch errors surface via the useQuery error path.
 *
 * Date math note: the server's `today` field is Asia/Jerusalem midnight-to-midnight
 * (D-03: strict today, not rolling 24h). Clients should use this field when
 * determining which day to display, not browser-local Date.now().
 */

import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Type definitions
// ---------------------------------------------------------------------------

/** A timed calendar event that may carry leave-by / Get Ready times (TIME-05). */
export interface TimedEvent {
  id: string
  title: string
  start: string       // ISO 8601 (Asia/Jerusalem)
  end: string         // ISO 8601 (Asia/Jerusalem)
  location?: string
  leave_by?: string   // ISO 8601 — "leave by" time for traffic-aware travel (TIME-05)
  get_ready_at?: string // ISO 8601 — start of Get Ready block (TIME-05)
}

/** Macros for a meal slot. All values are numeric (grams or kcal). */
export interface Macros {
  kcal: number
  protein_g: number
  carbs_g: number
  fat_g: number
  fiber_g: number
}

/**
 * A meal row in the timeline.
 *
 * IMPORTANT — TIME-03 / CLAUDE.md §6 invariant:
 * `slot_label` is a canonical slot name ("Breakfast", "Lunch", "Dinner").
 * It is NOT an eating time. The HealthKit/Lifesum canonical slot times
 * (08:00/12:00/20:00) are server-side metadata and MUST NOT be rendered
 * as "eaten at" times in any UI component.
 */
export interface MealItem {
  slot_label: string // e.g. "Breakfast", "Lunch", "Dinner"
  macros: Macros
}

/** Garmin morning stats — null before the daily sync runs (D-06). */
export interface GarminStats {
  sleep: number | null        // hours (float)
  hrv: number | null          // ms
  body_battery: number | null // 0-100 score
  resting_hr: number | null   // bpm
}

/**
 * Training plan item for today.
 *
 * `block_context` carries "Week N of 16 — Lower Body A" (TIME-04).
 * null means no training is scheduled (D-06: render PlaceholderCard).
 */
export interface TrainingItem {
  item: string          // e.g. "Lower Body A — Push/Pull/Legs"
  block_context: string // e.g. "Week 3 of 16 — Lower Body A"
}

/** Full response from GET /api/today. */
export interface TodayData {
  today: string          // ISO date "YYYY-MM-DD" in Asia/Jerusalem (D-03)
  calendar: {
    all_day: string[]    // All-day event titles, pinned at top (TIME-01)
    timed: TimedEvent[]  // Sorted chronologically by start (TIME-01)
  }
  garmin: GarminStats | null   // null → D-06 "Sleep stats syncing…" placeholder
  weather: string | null       // One-line summary (TIME-02); null = unavailable
  meals: MealItem[]            // Empty → D-06 "No meals logged yet today." placeholder
  training: TrainingItem | null // null → D-06 "No training scheduled today." placeholder
  coach_note: string | null    // null → D-06 "Coach note coming after your morning briefing."
  nutrition_totals: Macros     // Running day totals for glance rail (TIME-08)
}

// ---------------------------------------------------------------------------
// Fetch function
// ---------------------------------------------------------------------------

/**
 * Fetch today's full-day snapshot from /api/today.
 *
 * Used by useToday() hook — do not call directly in components.
 * apiFetch handles credentials: 'include' and 401 → redirect to sign-in.
 */
export async function fetchToday(): Promise<TodayData> {
  return apiFetch<TodayData>('/api/today')
}
