/**
 * BarChart.test.tsx — D-08 gap-rendering regression guard, mirrors
 * LineChart.test.tsx. A `y === null` value must render NO bar (never a
 * zero-height bar), and the internal tooltip must still surface the gap as
 * "No data" so it's discoverable (D-08).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { BarChart } from './BarChart'

const POINTS = [
  { x: 'd1', y: 5 },
  { x: 'd2', y: 6 },
  { x: 'd3', y: null },
  { x: 'd4', y: 8 },
  { x: 'd5', y: 7 },
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

describe('BarChart', () => {
  it('gap: renders no bar (not a zero-height bar) for a null value', () => {
    const { container } = render(<BarChart points={POINTS} color="#38BDF8" height={160} />)
    const rects = container.querySelectorAll('svg rect')
    expect(rects.length).toBe(4)
    rects.forEach((r) => {
      expect(Number(r.getAttribute('height'))).toBeGreaterThan(0)
    })
    const nullBar = container.querySelector('svg rect[data-point-index="2"]')
    expect(nullBar).toBeNull()
  })

  it("tooltip: hovering near a real bar shows a tooltip with that bar's exact value and x label", () => {
    const { container } = render(<BarChart points={POINTS} color="#38BDF8" height={160} />)
    const el = container.querySelector('[data-testid="bar-chart"]') as HTMLElement
    mockRect(el)
    fireEvent.mouseMove(el, { clientX: 66 }) // nearest d1 slot center
    expect(screen.getByText('d1')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('nodata: hovering at the gapped x-position shows a "No data" tooltip with no value', () => {
    const { container } = render(<BarChart points={POINTS} color="#38BDF8" height={160} />)
    const el = container.querySelector('[data-testid="bar-chart"]') as HTMLElement
    mockRect(el)
    fireEvent.mouseMove(el, { clientX: 300 }) // nearest d3 slot center (null)
    expect(screen.getByText('d3')).toBeInTheDocument()
    expect(screen.getByText('No data')).toBeInTheDocument()
  })
})
