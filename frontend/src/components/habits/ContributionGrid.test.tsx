/**
 * ContributionGrid.test.tsx — regression guard for WR-03.
 *
 * Bug: a fixed 52×7 (364-slot) grid dropped the 365th cell (today) into an
 * invisible implicit column, so a brand-new habit's only coloured cell (today's
 * check-off) never showed. The grid must render EVERY cell — including the last
 * one — and pad the front so cells align to weekday rows.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { ContributionGrid } from './ContributionGrid'
import type { GridCell } from '../../api/habits'

/** Build `n` consecutive daily cells ending on `endIso`, last one `done`. */
function makeCells(endIso: string, n: number): GridCell[] {
  const [y, m, d] = endIso.split('-').map(Number)
  const end = new Date(y, m - 1, d)
  const cells: GridCell[] = []
  for (let i = n - 1; i >= 0; i--) {
    const dt = new Date(end)
    dt.setDate(end.getDate() - i)
    const iso = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
    cells.push({ date: iso, state: i === 0 ? 'done' : 'not-scheduled' })
  }
  return cells
}

describe('ContributionGrid — WR-03', () => {
  it('renders the final (today) cell instead of dropping it off the grid', () => {
    const today = '2026-07-02'
    const cells = makeCells(today, 365)
    render(<ContributionGrid cells={cells} />)
    // Today's done cell must exist (previously overflowed into an implicit column)
    expect(screen.getByLabelText(`${today}: done`)).toBeInTheDocument()
  })

  it('renders exactly one gridcell per data cell (pads are non-cells)', () => {
    const cells = makeCells('2026-07-02', 365)
    render(<ContributionGrid cells={cells} />)
    expect(screen.getAllByRole('gridcell')).toHaveLength(365)
  })

  it('handles an empty history without crashing', () => {
    render(<ContributionGrid cells={[]} />)
    expect(screen.queryAllByRole('gridcell')).toHaveLength(0)
  })
})
