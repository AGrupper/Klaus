/**
 * SlotAdherenceGrid.test.tsx — regression guard for the D-13/D-16 slot-label
 * invariant: cells and aria-labels must key on the fueling-slot LABEL only,
 * NEVER a derived clock time (CLAUDE.md §6).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { SlotAdherenceGrid } from './SlotAdherenceGrid'
import type { SlotAdherenceGridData } from '../../../api/health'

function makeData(): SlotAdherenceGridData {
  return {
    slot_labels: ['Post-lift', 'Evening'],
    dates: ['2026-07-06', '2026-07-07'],
    grid: [
      {
        slot_label: 'Post-lift',
        cells: [
          { date: '2026-07-06', hit: true },
          { date: '2026-07-07', hit: false },
        ],
      },
      {
        slot_label: 'Evening',
        cells: [
          { date: '2026-07-06', hit: false },
          { date: '2026-07-07', hit: true },
        ],
      },
    ],
  }
}

describe('SlotAdherenceGrid — D-13/D-16 slot-label invariant', () => {
  it('keys cells on the slot LABEL — aria-label carries the slot name', () => {
    render(<SlotAdherenceGrid data={makeData()} onDaySelect={() => {}} />)
    expect(screen.getByLabelText('2026-07-06, Post-lift: logged')).toBeInTheDocument()
    expect(screen.getByLabelText('2026-07-07, Evening: logged')).toBeInTheDocument()
  })

  it('never renders a clock-time string anywhere in the grid', () => {
    const { container } = render(<SlotAdherenceGrid data={makeData()} onDaySelect={() => {}} />)
    expect(container.innerHTML).not.toMatch(/[0-2][0-9]:[0-5][0-9]/)
  })

  it('hit and miss cells use different fill colors', () => {
    render(<SlotAdherenceGrid data={makeData()} onDaySelect={() => {}} />)
    const hitCell = screen.getByLabelText('2026-07-06, Post-lift: logged')
    const missCell = screen.getByLabelText('2026-07-07, Post-lift: not logged')
    expect(hitCell.style.backgroundColor).not.toBe(missCell.style.backgroundColor)
  })

  it('tapping a cell fires onDaySelect with that date', () => {
    const onDaySelect = vi.fn()
    render(<SlotAdherenceGrid data={makeData()} onDaySelect={onDaySelect} />)
    const cell = screen.getByLabelText('2026-07-06, Post-lift: logged')
    fireEvent.click(cell)
    expect(onDaySelect).toHaveBeenCalledWith('2026-07-06')
  })

  it('renders exactly one gridcell per date x slot combination', () => {
    render(<SlotAdherenceGrid data={makeData()} onDaySelect={() => {}} />)
    expect(screen.getAllByRole('gridcell')).toHaveLength(4)
  })

  it('renders an empty state when there are no dates', () => {
    render(
      <SlotAdherenceGrid
        data={{ slot_labels: [], dates: [], grid: [] }}
        onDaySelect={() => {}}
      />,
    )
    expect(screen.queryAllByRole('gridcell')).toHaveLength(0)
    expect(screen.getByText('No meals logged yet in this range.')).toBeInTheDocument()
  })
})
