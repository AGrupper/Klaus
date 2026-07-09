/**
 * LineChart.tsx — Hand-rolled inline SVG — no chart library (D-04, resolved
 * in 30-UI-SPEC), matching the ContributionGrid precedent.
 *
 * Renders one or more series as SVG `<path>` segments. A `y === null` point
 * NEVER interpolates and NEVER zero-fills — the path is split into a NEW
 * `<path>` element at every null (literal path splitting, not a single path
 * with moveTo gaps, which some renderers still visually connect), producing
 * a genuine visible break in the line (D-08). Supports a dashed second
 * series (7-day baseline overlay, D-18) via `series.dashed` and an optional
 * dashed horizontal reference line (target, D-15) in `textSecondary`.
 *
 * X-axis: points are laid out at equal pixel spacing by index. The backend
 * pre-aggregates to daily (<=90d) or weekly (>90d) points (D-07) and the
 * frontend never re-buckets client-side (T-30-03-01) — equal index spacing
 * renders both daily and weekly point sets identically without special-
 * casing, satisfying "render whatever points arrive."
 *
 * Tooltip: hovering (desktop) or tapping (phone) near a point renders
 * ChartTooltip internally with that point's exact x label + y value.
 * Hovering/tapping an x-position that lands on a gap (y === null) still
 * shows ChartTooltip, reading "No data" (D-08 — gaps are discoverable, not
 * silently invisible). Series colors are always supplied by the caller;
 * this file imports only neutral chrome tokens (textSecondary for the
 * reference line).
 */
import { useMemo, useRef, useState } from 'react'
import { textSecondary } from '../../tokens'
import { ChartTooltip } from './ChartTooltip'

export interface ChartPoint {
  x: string
  y: number | null
}

export interface ChartSeries {
  label: string
  color: string
  points: ChartPoint[]
  /** Dashed stroke (e.g. a 7-day rolling baseline overlay, D-18). */
  dashed?: boolean
}

export interface ReferenceLine {
  value: number
  label: string
}

export interface LineChartProps {
  series: ChartSeries[]
  referenceLine?: ReferenceLine
  /** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
  height: number
  /**
   * Formats a point's y value for the tooltip (e.g. pace seconds → "5:59/km").
   * Defaults to a bare number-to-string — callers pass unit/format-aware
   * functions so the tooltip never shows a raw, unitless value.
   */
  formatValue?: (y: number) => string
  /**
   * Invert the Y axis so a LOWER value plots HIGHER. Used for pace charts:
   * a faster pace (fewer sec/km) reads more naturally near the top, so a
   * rising line means "getting faster."
   */
  invertY?: boolean
}

const VIEW_WIDTH = 600
const PADDING = 8

export function LineChart({ series, referenceLine, height, formatValue, invertY }: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState<{
    index: number
    left: number
    top: number
    width: number
  } | null>(null)
  const fmt = formatValue ?? ((y: number) => String(y))

  const pointCount = series[0]?.points.length ?? 0

  // Y domain spans all series' non-null values (+ the reference line).
  const { minY, maxY } = useMemo(() => {
    const values: number[] = []
    for (const s of series) {
      for (const p of s.points) {
        if (p.y !== null) values.push(p.y)
      }
    }
    if (referenceLine) values.push(referenceLine.value)
    if (values.length === 0) return { minY: 0, maxY: 1 }
    const min = Math.min(...values)
    const max = Math.max(...values)
    return min === max ? { minY: min - 1, maxY: max + 1 } : { minY: min, maxY: max }
  }, [series, referenceLine])

  const xForIndex = (i: number) => {
    if (pointCount <= 1) return VIEW_WIDTH / 2
    return PADDING + (i / (pointCount - 1)) * (VIEW_WIDTH - PADDING * 2)
  }
  const yForValue = (v: number) => {
    const span = maxY - minY || 1
    const frac = (v - minY) / span
    // Default: higher value → higher on screen (smaller y). invertY flips it
    // so a lower value plots higher (pace charts — lower sec/km reads as up).
    return PADDING + (invertY ? frac : 1 - frac) * (height - PADDING * 2)
  }

  /**
   * Split a series' points into path-data segments, starting a NEW segment
   * every time y === null — the D-08 gap rule. Each segment is its own
   * `<path>` element so the null never bridges two real points.
   */
  function buildSegments(points: ChartPoint[]): string[] {
    const segments: string[] = []
    let current: string[] = []
    points.forEach((p, i) => {
      if (p.y === null) {
        if (current.length) {
          segments.push(current.join(' '))
          current = []
        }
        return
      }
      const cmd = `${current.length === 0 ? 'M' : 'L'}${xForIndex(i)},${yForValue(p.y)}`
      current.push(cmd)
    })
    if (current.length) segments.push(current.join(' '))
    return segments
  }

  function handlePointer(clientX: number) {
    const el = containerRef.current
    if (!el || pointCount === 0) return
    const rect = el.getBoundingClientRect()
    if (!rect.width) return
    const relX = ((clientX - rect.left) / rect.width) * VIEW_WIDTH
    let nearest = 0
    let nearestDist = Infinity
    for (let i = 0; i < pointCount; i++) {
      const dist = Math.abs(xForIndex(i) - relX)
      if (dist < nearestDist) {
        nearestDist = dist
        nearest = i
      }
    }
    const primary = series[0]
    const point = primary?.points[nearest]
    const left = (xForIndex(nearest) / VIEW_WIDTH) * rect.width
    const top =
      point && point.y !== null ? (yForValue(point.y) / height) * rect.height : rect.height / 2
    setActive({ index: nearest, left, top, width: rect.width })
  }

  const activePoint = active ? series[0]?.points[active.index] : null

  return (
    <div
      ref={containerRef}
      data-testid="line-chart"
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
        aria-label="Line chart"
      >
        {referenceLine && (
          <line
            x1={PADDING}
            x2={VIEW_WIDTH - PADDING}
            y1={yForValue(referenceLine.value)}
            y2={yForValue(referenceLine.value)}
            stroke={textSecondary}
            strokeDasharray="4 4"
            strokeWidth={1}
          />
        )}
        {series.map((s) =>
          buildSegments(s.points).map((d, i) => (
            <path
              key={`${s.label}-${i}`}
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? '2 3' : undefined}
            />
          ))
        )}
        {series.map((s) =>
          s.points.map((p, i) =>
            p.y === null ? null : (
              <circle
                key={`${s.label}-pt-${i}`}
                data-point-index={i}
                cx={xForIndex(i)}
                cy={yForValue(p.y)}
                r={3}
                fill={s.color}
              />
            )
          )
        )}
      </svg>
      {active && activePoint && (
        <ChartTooltip
          label={activePoint.x}
          value={activePoint.y === null ? null : fmt(activePoint.y)}
          left={active.left}
          top={active.top}
          containerWidth={active.width}
        />
      )}
    </div>
  )
}
