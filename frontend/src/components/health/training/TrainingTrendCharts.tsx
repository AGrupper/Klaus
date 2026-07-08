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
          <BarChart points={strengthVolume} color={STRENGTH_COLOR} height={CHART_HEIGHT} />
        )}
      </ChartCard>
      <ChartCard title="Pace & Distance">
        {runTrend.length === 0 ? (
          <ChartEmptyState text="No data for this range." height={CHART_HEIGHT} />
        ) : (
          <LineChart
            series={[{ label: 'Pace', color: RUN_COLOR, points: runTrend }]}
            height={CHART_HEIGHT}
          />
        )}
      </ChartCard>
    </div>
  )
}
