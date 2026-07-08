/**
 * health.ts — Type contracts + fetch functions for GET /api/health/{training,nutrition,sleep}.
 *
 * These three endpoints (Plan 30-02 / HLTH-01..03) mirror the /api/today
 * composition pattern: the server pre-aggregates everything (weekly bucketing,
 * targets, gap markers) so the frontend only ever renders — it never re-derives
 * totals/averages client-side (30-UI-SPEC.md § Interaction Contracts).
 *
 * Range semantics (D-05): `range` is a closed 4-value set. Ranges over 90 days
 * (`1y`) return weekly-bucketed `{x, y}` points instead of daily ones (D-07) —
 * the frontend never re-buckets, it renders whatever points the API returns.
 *
 * Gap semantics (D-08, cross-cutting): any `y: number | null` in a trend series
 * means "no data for this point" — NOT zero. Chart components must render a
 * visible break, never a zero-value point and never an interpolated bridge.
 *
 * Slot-label semantics (CLAUDE.md §6 / D-13/D-16): nutrition slot labels
 * ("Breakfast", "Post-lift") are canonical fueling-slot NAMES, never clock
 * times. HealthKit/Lifesum's underlying 08:00/12:00/20:00 timestamps are
 * server-side-only metadata and never reach the wire as times.
 */

import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

/** Closed set of valid range values (D-05) — server allowlists, so must the client. */
export type RangeKey = '7d' | '30d' | '90d' | '1y'

/**
 * One point in a trend series. `y: null` is a gap (D-08) — never a zero-fill,
 * never interpolated. `x` is an ISO date ("YYYY-MM-DD") for daily series, or
 * the first day of an ISO week for weekly-bucketed series (>90d ranges, D-07).
 */
export interface TrendPoint {
  x: string
  y: number | null
}

// ---------------------------------------------------------------------------
// GET /api/health/training (HLTH-01)
// ---------------------------------------------------------------------------

/** One set within a strength exercise (StrengthSessionStore, via Hevy normalizer). */
export interface StrengthSet {
  index: number | null
  type: string | null // e.g. "working" | "warmup"
  weight_kg: number | null
  reps: number | null
  rpe: number | null
  distance_meters: number | null
}

/** One exercise within a strength session, with derived working-set metrics. */
export interface StrengthExercise {
  name: string
  template_id?: string
  notes?: string
  sets: StrengthSet[]
  set_count: number
  top_set: { weight_kg: number; reps: number } | null
  est_1rm: number | null
  volume_kg: number
}

/** A strength training log entry (modality: 'strength'). */
export interface StrengthLogEntry {
  modality: 'strength'
  date: string // YYYY-MM-DD
  workout_id: string
  title?: string
  description?: string
  duration_min?: number | null
  exercises?: StrengthExercise[]
  total_volume_kg: number
}

/** One lap/split within a run (RunDetailStore, via Garmin normalizer). */
export interface RunLap {
  [key: string]: unknown // pace/HR/distance fields per-lap; drill-down scope (Plan 30-05)
}

/** A run training log entry (modality: 'run'). */
export interface RunLogEntry {
  modality: 'run'
  date: string // YYYY-MM-DD
  activity_id: string
  type?: string | null
  duration_sec?: number | null
  distance_m?: number | null
  avg_pace_sec_per_km: number | null
  summary?: Record<string, unknown>
  splits?: RunLap[]
  has_dynamics?: boolean
}

/** A benchmark training log entry (modality: 'benchmark') — BenchmarkStore. */
export interface BenchmarkLogEntry {
  modality: 'benchmark'
  date: string // YYYY-MM-DD
  facet: string
  value: number
  unit?: string
  block_id?: string
  notes?: string
  /** Prior same-facet result strictly older than this entry's date, or null if none exists. */
  previous_value: number | null
}

/** One entry in the mixed reverse-chronological training log (D-09, D-12). */
export type TrainingLogEntryData = StrengthLogEntry | RunLogEntry | BenchmarkLogEntry

/** One training block divider row. */
export interface TrainingBlock {
  block_id?: string
  /** Sequential 1-based number (BlockStore itself stores no number field). */
  block_number: number
  label: string
  start_date: string
  end_date: string
}

/** Full response from GET /api/health/training. */
export interface TrainingHistoryData {
  range: RangeKey | string
  /** Reverse-chronological (newest first), interleaved strength/run/benchmark (D-09). */
  entries: TrainingLogEntryData[]
  blocks: TrainingBlock[]
  /** Weekly-volume trend (kg, summed per date/week). Gaps are null (D-08). */
  strength_volume: TrendPoint[]
  /** Run pace trend (sec/km, lower = faster; averaged per date/week). Gaps are null (D-08). */
  run_trend: TrendPoint[]
}

// ---------------------------------------------------------------------------
// GET /api/health/nutrition (HLTH-02)
// ---------------------------------------------------------------------------

/** The 5 macro series keys returned under `series`. */
export type NutritionMacroKey = 'calories' | 'protein_g' | 'carbs_g' | 'fat_g' | 'fiber_g'

/** Range-wide macro averages (averaged over days WITH data only, never zero-filled). */
export interface NutritionAverages {
  days_with_data: number
  calories?: number
  protein_g?: number
  carbs_g?: number
  fat_g?: number
  fiber_g?: number
}

/**
 * Nutrition targets from UserProfileStore.nutrition_targets, silent-omitted
 * (empty object) when the profile carries none (mirrors D-15).
 *
 * `calories` is either a literal stored target or a derived value
 * (protein_g*4 + carbs_g*4 + fat_g*9) — `calories_target_derived` is true
 * only in the derived case (RESEARCH.md Open Question A4).
 */
export interface NutritionTargets {
  calories?: number
  calories_target_derived?: boolean
  protein_g?: number
  carbs_g?: number
  fat_g?: number
  fiber_g_floor?: number
  protein_g_per_kg?: [number, number]
  protein_g_floor?: number
  [key: string]: unknown
}

/** One row (fueling slot) of the slot-adherence grid. */
export interface SlotAdherenceRow {
  /** Canonical fueling-slot LABEL — never a clock time (CLAUDE.md §6). */
  slot_label: string
  cells: { date: string; hit: boolean }[]
}

/** The D-13 per-slot-per-day hit matrix — rows are slots, columns are days. */
export interface SlotAdherenceGridData {
  slot_labels: string[]
  dates: string[]
  grid: SlotAdherenceRow[]
}

/** Full response from GET /api/health/nutrition. */
export interface NutritionDetailData {
  range: RangeKey | string
  /** Per-macro trend series. A date absent from a series is a gap (D-08) — see missing_dates. */
  series: Record<NutritionMacroKey, TrendPoint[]>
  /** Dates with zero logged meals in range — never appear as a zero point in `series` (D-08). */
  missing_dates: string[]
  averages: NutritionAverages
  targets: NutritionTargets
  /** Average protein per kg bodyweight over the range, or undefined if not computable. */
  avg_protein_g_per_kg?: number
  slot_adherence: SlotAdherenceGridData
}

// ---------------------------------------------------------------------------
// GET /api/health/sleep (HLTH-03)
// ---------------------------------------------------------------------------

/** The 5 sleep/recovery series keys returned under `series`. */
export type SleepSeriesKey =
  | 'hrv_overnight'
  | 'sleep_score'
  | 'sleep_duration'
  | 'body_battery_max'
  | 'hrv_baseline'

/** Most recent daily_biometrics row, or null if the range has no rows. */
export interface SleepHeaderStats {
  date: string
  hrv_overnight: number | null
  sleep_score: number | null
  body_battery_max: number | null
  resting_hr: number | null
  training_readiness: number | null
}

/** Full response from GET /api/health/sleep. */
export interface SleepRecoveryData {
  range: RangeKey | string
  /**
   * Series keyed by metric. `hrv_baseline` is the 7-day rolling baseline
   * overlay (falls back to a rolling median of hrv_overnight when the stored
   * column is sparse — D-18). Gaps are null (D-08 — watch-not-worn != HRV of 0).
   */
  series: Record<SleepSeriesKey, TrendPoint[]>
  header_stats: SleepHeaderStats | null
  /**
   * True iff `daily_biometrics` has EVER had a row — distinct from "no rows
   * in this range". False means the biometric-sync cron has never populated
   * the table (D-19 pipeline-not-live guard); render the "isn't syncing yet"
   * placeholder instead of the normal per-chart empty state in that case.
   */
  pipeline_active: boolean
}

// ---------------------------------------------------------------------------
// Fetch functions
// ---------------------------------------------------------------------------

/**
 * Fetch merged strength+run+benchmark training log + block dividers + trends.
 * Used by useTrainingHistory() — do not call directly in components.
 */
export async function fetchTrainingHistory(range: RangeKey): Promise<TrainingHistoryData> {
  return apiFetch<TrainingHistoryData>(`/api/health/training?range=${range}`)
}

/**
 * Fetch per-day/weekly macro series + slot-adherence grid + targets.
 * Used by useNutritionDetail() — do not call directly in components.
 */
export async function fetchNutritionDetail(range: RangeKey): Promise<NutritionDetailData> {
  return apiFetch<NutritionDetailData>(`/api/health/nutrition?range=${range}`)
}

/**
 * Fetch HRV/sleep/body-battery trend series + header stats + pipeline_active.
 * Used by useSleepRecovery() — do not call directly in components.
 */
export async function fetchSleepRecovery(range: RangeKey): Promise<SleepRecoveryData> {
  return apiFetch<SleepRecoveryData>(`/api/health/sleep?range=${range}`)
}
