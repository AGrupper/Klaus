/**
 * NutritionDetailPage.tsx — Root content for the Nutrition sub-tab (HLTH-02).
 *
 * RangeToggle at top (owns useState<RangeKey>('30d') — NOT persisted, D-06),
 * then a MacroChipRow (owns useState<NutritionMacroKey>('calories'), D-14),
 * a MacroTrendChart for the selected metric (dashed target + avg-vs-target
 * summary, D-15), and a contribution-style SlotAdherenceGrid under the
 * "Fueling Slot Adherence" heading (D-13). Changing the range triggers a new
 * useNutritionDetail query key; Skeleton blocks replace the chart + grid
 * during the initial fetch for a range.
 *
 * Both a MacroTrendChart point tap and a SlotAdherenceGrid cell tap open a
 * single shared DayDrilldownSheet for the chosen date (D-16). The current
 * /api/health/nutrition response carries day-level macro totals + a slot-hit
 * matrix but no per-meal macro breakdown, so the sheet receives the slots
 * that were hit that day (labels only, never a clock time — CLAUDE.md §6) plus
 * the day's macro totals reconstructed from the per-macro series, all rendered
 * verbatim (T-30-06-02, no client re-derivation).
 *
 * Error state copy per 30-UI-SPEC Copywriting Contract:
 * "Couldn't load nutrition data — pull to refresh."
 */
import { useState } from 'react'
import { useNutritionDetail } from '../../../hooks/useHealth'
import { RangeToggle } from '../RangeToggle'
import { MacroChipRow } from './MacroChipRow'
import { MacroTrendChart } from './MacroTrendChart'
import { SlotAdherenceGrid } from './SlotAdherenceGrid'
import { DayDrilldownSheet } from './DayDrilldownSheet'
import type { DayDrilldownMeal, DayMacros } from './DayDrilldownSheet'
import { Skeleton } from '../../shared/Skeleton'
import { textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type {
  RangeKey,
  NutritionMacroKey,
  NutritionDetailData,
} from '../../../api/health'

/**
 * Target lookup for the selected metric. Every macro maps 1:1 onto a
 * `targets` key except fiber, whose target is a floor (`fiber_g_floor`).
 */
function targetFor(
  metric: NutritionMacroKey,
  targets: NutritionDetailData['targets'],
): number | undefined {
  const key = metric === 'fiber_g' ? 'fiber_g_floor' : metric
  const value = targets[key]
  return typeof value === 'number' ? value : undefined
}

/** Reconstruct a day's macro totals from the per-macro series (verbatim, no re-derivation). */
function dayTotalsFor(date: string, series: NutritionDetailData['series']): DayMacros {
  const at = (metric: NutritionMacroKey): number | null => {
    const point = series[metric]?.find((p) => p.x === date)
    return point ? point.y : null
  }
  return {
    kcal: at('calories'),
    protein_g: at('protein_g'),
    carbs_g: at('carbs_g'),
    fat_g: at('fat_g'),
    fiber_g: at('fiber_g'),
  }
}

/** Slots with a logged meal on `date`, in grid (slot) order — labels only. */
function mealsFor(date: string, slot: NutritionDetailData['slot_adherence']): DayDrilldownMeal[] {
  return slot.grid
    .filter((row) => row.cells.some((cell) => cell.date === date && cell.hit))
    .map((row) => ({ slot_label: row.slot_label }))
}

function LoadingSkeletons() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <Skeleton className="h-9 w-full" aria-label="Loading nutrition data…" />
      <Skeleton className="h-[200px] w-full" aria-label="Loading nutrition data…" />
      <Skeleton className="h-[140px] w-full" aria-label="Loading nutrition data…" />
    </div>
  )
}

export function NutritionDetailPage() {
  const [range, setRange] = useState<RangeKey>('30d')
  const [metric, setMetric] = useState<NutritionMacroKey>('calories')
  const [openDate, setOpenDate] = useState<string | null>(null)
  const { data, isLoading, isError } = useNutritionDetail(range)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <RangeToggle value={range} onChange={setRange} />

      {isError ? (
        <p
          style={{
            margin: 0,
            textAlign: 'center',
            padding: '24px 16px',
            fontSize: typography.label.fontSize,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          Couldn&apos;t load nutrition data — pull to refresh.
        </p>
      ) : isLoading || !data ? (
        <LoadingSkeletons />
      ) : (
        <>
          <MacroChipRow metric={metric} onChange={setMetric} />
          <MacroTrendChart
            metric={metric}
            points={data.series[metric] ?? []}
            avg={data.averages[metric]}
            target={targetFor(metric, data.targets)}
            avgProteinGPerKg={metric === 'protein_g' ? data.avg_protein_g_per_kg : undefined}
            onDaySelect={setOpenDate}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <h2
              style={{
                margin: 0,
                fontSize: typography.label.fontSize,
                lineHeight: typography.label.lineHeight,
                fontWeight: 600,
                color: textPrimary,
                fontFamily,
              }}
            >
              Fueling Slot Adherence
            </h2>
            <SlotAdherenceGrid data={data.slot_adherence} onDaySelect={setOpenDate} />
          </div>

          {openDate && (
            <DayDrilldownSheet
              date={openDate}
              meals={mealsFor(openDate, data.slot_adherence)}
              dayTotals={dayTotalsFor(openDate, data.series)}
              open={openDate !== null}
              onClose={() => setOpenDate(null)}
            />
          )}
        </>
      )}
    </div>
  )
}
