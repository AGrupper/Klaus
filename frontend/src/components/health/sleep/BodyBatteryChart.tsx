/**
 * BodyBatteryChart.tsx — Single-series body battery line, D-19.
 *
 * `ChartCard` wraps `LineChart` with one series, #4ADE80 — deliberately a
 * different green than the reserved "connected/message-sent" token so
 * "body battery" is never confused with that other semantic meaning
 * (30-UI-SPEC Color § Sleep & recovery charts). Renders `ChartEmptyState`
 * with the per-chart empty copy when the series has zero points.
 */
import { ChartCard } from '../../charts/ChartCard'
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import { LineChart } from '../../charts/LineChart'
import type { TrendPoint } from '../../../api/health'

const BODY_BATTERY_COLOR = '#4ADE80'

interface BodyBatteryChartProps {
  points: TrendPoint[]
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height: number
}

export function BodyBatteryChart({ points, height }: BodyBatteryChartProps) {
  const isEmpty = points.every((p) => p.y === null)

  return (
    <ChartCard title="Body Battery">
      {isEmpty ? (
        <ChartEmptyState text="No body battery data for this range." height={height} />
      ) : (
        <LineChart
          series={[{ label: 'Body battery', color: BODY_BATTERY_COLOR, points }]}
          height={height}
        />
      )}
    </ChartCard>
  )
}
