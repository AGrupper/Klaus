/**
 * TrainingTrendCharts.tsx — The two training trend ChartCards (D-11):
 * "Weekly Volume" (strength, BarChart, #FB923C) and "Pace & Distance"
 * (running, LineChart, #38BDF8).
 *
 * Layout: side-by-side 2-column grid on desktop, stacked on phone —
 * driven entirely by Tailwind classes (grid md:grid-cols-2), NEVER inline
 * style={{ display }} (Phase 27 UAT lesson). Chart height 160px (phone-
 * safe value; 30-UI-SPEC Spacing § chart height).
 *
 * Series colors are passed as props into the shared chart primitives —
 * never hardcoded inside components/charts/ (30-03 contract). A series
 * with zero points renders ChartEmptyState in place of its chart
 * ("No data for this range."); null points inside a non-empty series
 * render as visible breaks via LineChart's D-08 gap-split paths.
 */
import { ChartCard } from '../../charts/ChartCard'
import { LineChart } from '../../charts/LineChart'
import { BarChart } from '../../charts/BarChart'
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import type { TrendPoint } from '../../../api/health'

const STRENGTH_COLOR = '#FB923C'
const RUN_COLOR = '#38BDF8'
const CHART_HEIGHT = 160

/** Strength volume (total_volume_kg) → "6,106 kg". */
function formatVolumeKg(v: number): string {
  return `${Math.round(v).toLocaleString()} kg`
}

/**
 * Run pace (avg_pace_sec_per_km) → "m:ss/km" (e.g. 358.8 → "5:59/km").
 * The API sends pace as seconds-per-km; a raw number is meaningless to read,
 * so the tooltip renders the conventional min:sec running-pace format.
 */
function formatPaceSecPerKm(sec: number): string {
  const total = Math.round(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}/km`
}

interface TrainingTrendChartsProps {
  strengthVolume: TrendPoint[]
  runTrend: TrendPoint[]
}

export function TrainingTrendCharts({ strengthVolume, runTrend }: TrainingTrendChartsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <ChartCard title="Weekly Volume">
        {strengthVolume.length === 0 ? (
          <ChartEmptyState text="No data for this range." height={CHART_HEIGHT} />
        ) : (
          <BarChart
            points={strengthVolume}
            color={STRENGTH_COLOR}
            height={CHART_HEIGHT}
            formatValue={formatVolumeKg}
          />
        )}
      </ChartCard>
      {/* Title reflects what's actually plotted — the API's run trend is pace
          (sec/km) only; per-run distance lives in the log entries below. */}
      <ChartCard title="Run Pace">
        {runTrend.length === 0 ? (
          <ChartEmptyState text="No data for this range." height={CHART_HEIGHT} />
        ) : (
          <LineChart
            series={[{ label: 'Pace', color: RUN_COLOR, points: runTrend }]}
            height={CHART_HEIGHT}
            formatValue={formatPaceSecPerKm}
          />
        )}
      </ChartCard>
    </div>
  )
}
