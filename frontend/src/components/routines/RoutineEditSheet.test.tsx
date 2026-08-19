/**
 * RoutineEditSheet.test.tsx — the "Remind me" switch (2026-08-19).
 *
 * A reminder fires at the routine's anchor_time, so the switch is meaningless
 * without one. These cover the coupling in both directions: the switch is
 * inert until a time is set, and clearing the time disarms the reminder on
 * save rather than storing one that could never fire.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { RoutineEditSheet } from './RoutineEditSheet'
import type { Routine } from '../../api/routines'

const createMutate = vi.fn()
const editMutate = vi.fn()

vi.mock('../../hooks/useRoutines', () => ({
  useCreateRoutine: () => ({ mutate: createMutate }),
  useEditRoutine: () => ({ mutate: editMutate }),
  useDeleteRoutine: () => ({ mutate: vi.fn() }),
}))

vi.mock('../../store/undoStore', () => ({
  useUndoStore: (selector: (state: { show: () => void }) => unknown) =>
    selector({ show: vi.fn() }),
}))

const ROUTINE: Routine = {
  id: 'r1',
  name: 'Nightly routine',
  emoji: '🌙',
  order: 1,
  anchor_time: '21:30',
  color: '#4C4C8F',
  remind: true,
  streak: 3,
  done_today: false,
  scheduled_today: 2,
  completed_today: 1,
  habits: [],
}

beforeEach(() => {
  createMutate.mockClear()
  editMutate.mockClear()
})

describe('RoutineEditSheet reminder switch', () => {
  it('is off and inert until a time of day is set', () => {
    render(<RoutineEditSheet routine={null} open onClose={vi.fn()} />)

    const toggle = screen.getByRole('switch', { name: 'Remind me' })
    expect(toggle).toBeDisabled()
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('Set a time of day first.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Time of day'), { target: { value: '07:00' } })
    expect(toggle).toBeEnabled()
    expect(
      screen.getByText('A notification at 07:00, only if anything is still open.'),
    ).toBeInTheDocument()
  })

  it('saves an armed reminder on a new routine', () => {
    render(<RoutineEditSheet routine={null} open onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Deep work' } })
    fireEvent.change(screen.getByLabelText('Time of day'), { target: { value: '09:00' } })
    fireEvent.click(screen.getByRole('switch', { name: 'Remind me' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create routine' }))

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ anchor_time: '09:00', remind: true }),
    )
  })

  it('seeds from the routine and disarms when the time is cleared', () => {
    render(<RoutineEditSheet routine={ROUTINE} open onClose={vi.fn()} />)

    expect(screen.getByRole('switch', { name: 'Remind me' })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    fireEvent.change(screen.getByLabelText('Time of day'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(editMutate).toHaveBeenCalledWith({
      id: 'r1',
      input: expect.objectContaining({ anchor_time: null, remind: false }),
    })
  })
})
