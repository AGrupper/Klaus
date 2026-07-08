/**
 * SleepChart.tsx — Sleep score line + sleep duration bars combined in one
 * chart card (D-17): recovery is read as a single vertical narrative, not
 * two separate cards.
 *
 * LineChart (score, #38BDF8) and BarChart (duration, #2DD4BF) share the
 * same VIEW_WIDTH/height coordinate system (both hard-code `viewBox="0 0
 * 600 {height}"`), so overlaying them absolutely-positioned within one
 * container produces one combined canvas without modifying either shared
 * chart primitive (LineChart.tsx/BarChart.tsx are 30-03 shared toolkit
 * files, out of scope for this plan). Bars render behind, the score line
 * renders on top. Renders `ChartEmptyState` with the per-chart empty copy
 * when both series have zero points.
 */
import { ChartCard } from '../../charts/ChartCard'
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import { LineChart } from '../../charts/LineChart'
import { BarChart } from '../../charts/BarChart'
import type { TrendPoint } from '../../../api/health'

const SLEEP_SCORE_COLOR = '#38BDF8'
const SLEEP_DURATION_COLOR = '#2DD4BF'

interface SleepChartProps {
  score: TrendPoint[]
  duration: TrendPoint[]
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height: number
}

export function SleepChart({ score, duration, height }: SleepChartProps) {
  const isEmpty = score.every((p) => p.y === null) && duration.every((p) => p.y === null)

  return (
    <ChartCard title="Sleep">
      {isEmpty ? (
        <ChartEmptyState text="No sleep data for this range." height={height} />
      ) : (
        <div style={{ position: 'relative', width: '100%', height }}>
          {/* Bars render behind — visual layer only; the line chart on top
              owns pointer/tap hit-testing so a single tooltip surfaces the
              score value (D-04's "one active tooltip" contract). */}
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <BarChart points={duration} color={SLEEP_DURATION_COLOR} height={height} />
          </div>
          <div style={{ position: 'absolute', inset: 0 }}>
            <LineChart
              series={[{ label: 'Sleep score', color: SLEEP_SCORE_COLOR, points: score }]}
              height={height}
            />
          </div>
        </div>
      )}
    </ChartCard>
  )
}
