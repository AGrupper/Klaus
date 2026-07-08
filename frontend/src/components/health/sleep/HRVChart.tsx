/**
 * HRVChart.tsx — Dual-series HRV overlay: overnight (solid) + 7-day rolling
 * baseline (dashed), D-18.
 *
 * `ChartCard` wraps `LineChart` with two series per 30-UI-SPEC Color § Sleep
 * & recovery charts: overnight #38BDF8 solid, baseline #A78BFA dashed
 * (`stroke-dasharray: 2 3`, handled internally by LineChart's `dashed` prop).
 * The gap between the two lines IS the coaching signal Klaus's coaching
 * already uses (D-18) — both series render on the same chart, never split
 * into two cards. A legend row ("Overnight" / "7-day baseline") sits above
 * the chart so the two lines are identifiable without relying on color
 * alone. Renders `ChartEmptyState` with the per-chart empty copy when both
 * series have zero points.
 */
import { ChartCard } from '../../charts/ChartCard'
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import { LineChart } from '../../charts/LineChart'
import { textSecondary, typography, fontFamily } from '../../../tokens'
import type { TrendPoint } from '../../../api/health'

const HRV_OVERNIGHT_COLOR = '#38BDF8'
const HRV_BASELINE_COLOR = '#A78BFA'

interface HRVChartProps {
  overnight: TrendPoint[]
  baseline: TrendPoint[]
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height: number
}

function LegendRow() {
  const itemStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  } as const
  const labelStyle = {
    fontSize: typography.label.fontSize,
    fontWeight: typography.label.fontWeight,
    lineHeight: typography.label.lineHeight,
    color: textSecondary,
    fontFamily,
  } as const

  return (
    <div style={{ display: 'flex', gap: '16px', marginBottom: '8px' }}>
      <div style={itemStyle}>
        <span
          style={{ width: '12px', height: '2px', backgroundColor: HRV_OVERNIGHT_COLOR }}
          aria-hidden="true"
        />
        <span style={labelStyle}>Overnight</span>
      </div>
      <div style={itemStyle}>
        <span
          style={{
            width: '12px',
            height: '2px',
            backgroundColor: HRV_BASELINE_COLOR,
            backgroundImage: `repeating-linear-gradient(90deg, ${HRV_BASELINE_COLOR} 0 2px, transparent 2px 4px)`,
          }}
          aria-hidden="true"
        />
        <span style={labelStyle}>7-day baseline</span>
      </div>
    </div>
  )
}

export function HRVChart({ overnight, baseline, height }: HRVChartProps) {
  const isEmpty =
    overnight.every((p) => p.y === null) && baseline.every((p) => p.y === null)

  return (
    <ChartCard title="HRV">
      <LegendRow />
      {isEmpty ? (
        <ChartEmptyState text="No HRV data for this range." height={height} />
      ) : (
        <LineChart
          series={[
            { label: 'Overnight', color: HRV_OVERNIGHT_COLOR, points: overnight },
            { label: '7-day baseline', color: HRV_BASELINE_COLOR, points: baseline, dashed: true },
          ]}
          height={height}
        />
      )}
    </ChartCard>
  )
}
