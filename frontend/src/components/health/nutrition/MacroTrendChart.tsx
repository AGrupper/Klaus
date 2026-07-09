/**
 * MacroTrendChart.tsx — ChartCard + LineChart for the currently selected
 * nutrition metric, with a dashed target reference line and an avg-vs-target
 * summary row (30-UI-SPEC Component Inventory § MacroTrendChart, D-14/D-15).
 *
 * Unlogged days are gaps — the caller passes the metric's TrendPoint[]
 * verbatim (with null y-values for unlogged days) straight into LineChart,
 * which splits the path at every null (D-08, T-30-06-03) — never a zero-fill.
 *
 * The summary row renders the server-computed average/target/g-per-kg values
 * verbatim (T-30-06-02) — no client re-derivation.
 *
 * Tapping a point calls onDaySelect(date); the day-drilldown sheet itself is
 * owned by the page (NutritionDetailPage, Task 3). Hit-testing mirrors
 * LineChart's own equal-index-spacing nearest-point math (index scaled by the
 * click's fractional x-position within the chart's own bounding box) since
 * LineChart does not expose a click callback of its own — it only manages its
 * internal hover/tap tooltip.
 */
import { ChartCard } from '../../charts/ChartCard'
import { LineChart } from '../../charts/LineChart'
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import { textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { NutritionMacroKey, TrendPoint } from '../../../api/health'
import { MACRO_COLORS, MACRO_LABELS } from './MacroChipRow'

/** Formats a metric value with its unit — kcal for calories, grams otherwise. */
function formatValue(metric: NutritionMacroKey, value: number): string {
  const rounded = Math.round(value)
  return metric === 'calories' ? `${rounded} kcal` : `${rounded}g`
}

interface MacroTrendChartProps {
  metric: NutritionMacroKey
  points: TrendPoint[]
  /** Range average for the selected metric (averages[metric] from the API, verbatim). */
  avg?: number
  /** Target value for the selected metric (targets[metric] from the API, verbatim). */
  target?: number
  /** Protein-only: average protein per kg bodyweight, appended to the summary row. */
  avgProteinGPerKg?: number
  /**
   * Tap-a-point → open that day's drilldown. Omitted when the series is
   * weekly-bucketed (range=1y), where a point is a week not a day, so a
   * day-drilldown would show wrong/empty data (WR-03).
   */
  onDaySelect?: (date: string) => void
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height?: number
}

export function MacroTrendChart({
  metric,
  points,
  avg,
  target,
  avgProteinGPerKg,
  onDaySelect,
  height = 160,
}: MacroTrendChartProps) {
  const hasData = points.some((p) => p.y !== null)
  const color = MACRO_COLORS[metric]
  const label = MACRO_LABELS[metric]

  function handleChartClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!onDaySelect) return
    const rect = e.currentTarget.getBoundingClientRect()
    if (!rect.width || points.length === 0) return
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    const index = Math.round(ratio * (points.length - 1))
    const point = points[index]
    if (point) onDaySelect(point.x)
  }

  return (
    <ChartCard>
      {hasData ? (
        <div onClick={handleChartClick}>
          <LineChart
            series={[{ label, color, points }]}
            referenceLine={target !== undefined ? { value: target, label: 'Target' } : undefined}
            height={height}
          />
        </div>
      ) : (
        <ChartEmptyState text="No nutrition data logged in this range." height={height} />
      )}

      {hasData && avg !== undefined && (
        <p
          style={{
            margin: '12px 0 0',
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          <span style={{ color: textPrimary, fontWeight: 600 }}>
            Avg {label}: {formatValue(metric, avg)}
          </span>
          {target !== undefined && ` · Target ${formatValue(metric, target)}`}
          {metric === 'protein_g' &&
            avgProteinGPerKg !== undefined &&
            ` · ${avgProteinGPerKg.toFixed(1)} g/kg bodyweight`}
        </p>
      )}
    </ChartCard>
  )
}
