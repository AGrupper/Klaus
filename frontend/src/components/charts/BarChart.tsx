/**
 * BarChart.tsx — Hand-rolled inline SVG — no chart library (D-04, resolved
 * in 30-UI-SPEC), matching the ContributionGrid precedent.
 *
 * Renders a single series as vertical bars. A `y === null` value renders NO
 * bar for that x — never a zero-height bar (D-08, same gap rule as
 * LineChart: a null means "no data," not "measured zero"). Tapping/hovering
 * near a bar — or at a gapped x-position — shows ChartTooltip internally,
 * same D-04 interaction contract as LineChart. Series color is supplied by
 * the caller; this file imports only neutral chrome tokens where needed.
 */
import { useRef, useState } from 'react'
import { ChartTooltip } from './ChartTooltip'
import type { ChartPoint } from './LineChart'

export interface BarChartProps {
  points: ChartPoint[]
  color: string
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height: number
}

const VIEW_WIDTH = 600
const PADDING = 8

export function BarChart({ points, color, height }: BarChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState<{ index: number; left: number; top: number } | null>(null)

  const nonNullValues = points.filter((p) => p.y !== null).map((p) => p.y as number)
  const maxY = nonNullValues.length ? Math.max(...nonNullValues, 0) : 1
  const minY = 0 // bars anchor at a zero baseline

  const n = points.length
  const slotWidth = n > 0 ? (VIEW_WIDTH - PADDING * 2) / n : VIEW_WIDTH
  const barWidth = Math.max(2, slotWidth * 0.6)

  const xForIndex = (i: number) => PADDING + slotWidth * i + slotWidth / 2
  const heightForValue = (v: number) => {
    const span = maxY - minY || 1
    return ((v - minY) / span) * (height - PADDING * 2)
  }

  function handlePointer(clientX: number) {
    const el = containerRef.current
    if (!el || n === 0) return
    const rect = el.getBoundingClientRect()
    if (!rect.width) return
    const relX = ((clientX - rect.left) / rect.width) * VIEW_WIDTH
    let nearest = 0
    let nearestDist = Infinity
    for (let i = 0; i < n; i++) {
      const dist = Math.abs(xForIndex(i) - relX)
      if (dist < nearestDist) {
        nearestDist = dist
        nearest = i
      }
    }
    const point = points[nearest]
    const left = (xForIndex(nearest) / VIEW_WIDTH) * rect.width
    const barH = point.y !== null ? heightForValue(point.y) : 0
    const barTop = height - PADDING - barH
    const top = (barTop / height) * rect.height
    setActive({ index: nearest, left, top })
  }

  const activePoint = active ? points[active.index] : null

  return (
    <div
      ref={containerRef}
      data-testid="bar-chart"
      style={{ position: 'relative', width: '100%', height }}
      onMouseMove={(e) => handlePointer(e.clientX)}
      onMouseLeave={() => setActive(null)}
      onClick={(e) => handlePointer(e.clientX)}
    >
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label="Bar chart"
      >
        {points.map((p, i) => {
          // Gap rule (D-08): a null value renders NO bar — never a
          // zero-height bar that would misrepresent "no data" as "measured
          // zero" (e.g. watch not worn vs. zero sleep duration).
          if (p.y === null) return null
          const barH = heightForValue(p.y)
          return (
            <rect
              key={p.x}
              data-point-index={i}
              x={xForIndex(i) - barWidth / 2}
              y={height - PADDING - barH}
              width={barWidth}
              height={barH}
              fill={color}
            />
          )
        })}
      </svg>
      {active && activePoint && (
        <ChartTooltip
          label={activePoint.x}
          value={activePoint.y === null ? null : String(activePoint.y)}
          left={active.left}
          top={active.top}
        />
      )}
    </div>
  )
}
