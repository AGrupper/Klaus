/**
 * LineChart.test.tsx — D-08 gap-rendering regression guard (mirrors
 * ContributionGrid.test.tsx's component-test convention).
 *
 * The highest-value test in this plan: a `y === null` point must produce a
 * visible break in the line (a NEW <path> segment), never a bridge across the
 * gap and never a zero-value point. Also covers the internal tooltip
 * (D-04 hover/tap) and its "No data" gap variant (D-08).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LineChart } from './LineChart'

/** Five points with a null in the middle — enough on each side of the gap
 * to prove a genuine visible line segment (M + L), not just a lone moveto. */
const POINTS = [
  { x: 'd1', y: 10 },
  { x: 'd2', y: 11 },
  { x: 'd3', y: null },
  { x: 'd4', y: 9 },
  { x: 'd5', y: 8 },
]

function mockRect(el: HTMLElement) {
  vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
    width: 600,
    height: 160,
    top: 0,
    left: 0,
    right: 600,
    bottom: 160,
    x: 0,
    y: 0,
    toJSON: () => {},
  } as DOMRect)
}

describe('LineChart', () => {
  it('gap: splits the path into a broken line at a null point — no bridge, no zero-fill', () => {
    const { container } = render(
      <LineChart series={[{ label: 'S', color: '#38BDF8', points: POINTS }]} height={160} />
    )
    const paths = container.querySelectorAll('svg path')
    // One segment before the gap (d1,d2), one after (d4,d5) — never a single
    // path bridging d1 through d5.
    expect(paths.length).toBe(2)
    paths.forEach((p) => {
      // Each segment is a real visible line (moveto + lineto), not a lone point.
      expect(p.getAttribute('d') || '').toContain('L')
    })
    // No marker rendered at the null x (d3) — the gap is never zero-filled.
    const markers = container.querySelectorAll('svg circle[data-point-index]')
    expect(markers.length).toBe(4)
    const nullMarker = container.querySelector('svg circle[data-point-index="2"]')
    expect(nullMarker).toBeNull()
  })

  it('renders dual-series with a dashed second series and a dashed reference line', () => {
    const { container } = render(
      <LineChart
        series={[
          { label: 'A', color: '#38BDF8', points: POINTS },
          { label: 'B', color: '#A78BFA', points: POINTS, dashed: true },
        ]}
        referenceLine={{ value: 9, label: 'Target: 9' }}
        height={160}
      />
    )
    const dashedPaths = container.querySelectorAll('svg path[stroke-dasharray]')
    expect(dashedPaths.length).toBeGreaterThan(0)
    const refLine = container.querySelector('svg line[stroke-dasharray]')
    expect(refLine).not.toBeNull()
  })

  it('tooltip: hovering near a real point shows a tooltip with that point\'s exact value and x label', () => {
    const { container } = render(
      <LineChart series={[{ label: 'S', color: '#38BDF8', points: POINTS }]} height={160} />
    )
    const el = container.querySelector('[data-testid="line-chart"]') as HTMLElement
    mockRect(el)
    fireEvent.mouseMove(el, { clientX: 8 }) // nearest d1
    expect(screen.getByText('d1')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
  })

  it('nodata: hovering at a gapped x-position shows a "No data" tooltip with no value', () => {
    const { container } = render(
      <LineChart series={[{ label: 'S', color: '#38BDF8', points: POINTS }]} height={160} />
    )
    const el = container.querySelector('[data-testid="line-chart"]') as HTMLElement
    mockRect(el)
    fireEvent.mouseMove(el, { clientX: 300 }) // nearest d3 (null)
    expect(screen.getByText('d3')).toBeInTheDocument()
    expect(screen.getByText('No data')).toBeInTheDocument()
  })

  it('invertY: a lower value plots HIGHER (pace orientation — faster on top)', () => {
    // With invertY, the smallest y value must render nearer the top (smaller
    // cy) than the largest — the opposite of the default orientation. Locks the
    // pace-chart UAT fix (faster pace = fewer sec/km = higher on the chart).
    const ascending = [
      { x: 'd1', y: 10 }, // smallest
      { x: 'd2', y: 20 },
      { x: 'd3', y: 30 }, // largest
    ]
    const { container } = render(
      <LineChart series={[{ label: 'Pace', color: '#38BDF8', points: ascending }]} height={160} invertY />
    )
    const circles = container.querySelectorAll('svg circle[data-point-index]')
    const cyFirst = Number(circles[0].getAttribute('cy')) // y=10 (smallest)
    const cyLast = Number(circles[2].getAttribute('cy')) // y=30 (largest)
    // Smaller cy = higher on screen. Inverted: the smallest value sits highest.
    expect(cyFirst).toBeLessThan(cyLast)
  })

  it('banded: point x-positions match BarChart slot centers (SleepChart overlay align)', () => {
    // WR-02: a banded line overlaid on a BarChart must sit centered over its
    // bars. Both use viewBox width 600, padding 8, slotWidth=(600-16)/n, center
    // at PADDING + slotWidth*i + slotWidth/2.
    const pts = [
      { x: 'd1', y: 1 },
      { x: 'd2', y: 2 },
      { x: 'd3', y: 3 },
    ]
    const { container } = render(
      <LineChart series={[{ label: 'S', color: '#38BDF8', points: pts }]} height={160} banded />
    )
    const circles = container.querySelectorAll('svg circle[data-point-index]')
    const slotWidth = (600 - 16) / 3
    const expectedCx = (i: number) => 8 + slotWidth * i + slotWidth / 2
    circles.forEach((c) => {
      const i = Number(c.getAttribute('data-point-index'))
      expect(Number(c.getAttribute('cx'))).toBeCloseTo(expectedCx(i), 3)
    })
  })

  it('formatValue: the tooltip renders the caller-formatted value, not the raw number', () => {
    // Regression for the raw-unitless-value UAT finding: pace seconds must be
    // formatted (e.g. m:ss/km), never dumped as a bare number.
    const { container } = render(
      <LineChart
        series={[{ label: 'Pace', color: '#38BDF8', points: [{ x: 'd1', y: 359 }] }]}
        height={160}
        formatValue={(y) => `${Math.floor(y / 60)}:${String(y % 60).padStart(2, '0')}/km`}
      />
    )
    const el = container.querySelector('[data-testid="line-chart"]') as HTMLElement
    mockRect(el)
    fireEvent.mouseMove(el, { clientX: 8 })
    expect(screen.getByText('5:59/km')).toBeInTheDocument()
    expect(screen.queryByText('359')).not.toBeInTheDocument()
  })
})
