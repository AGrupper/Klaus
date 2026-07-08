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
})
