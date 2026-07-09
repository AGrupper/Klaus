/**
 * TrainingLog.test.tsx — TDD RED/GREEN cycle for the mixed reverse-chronological
 * training log (D-09, D-12).
 *
 * Asserts:
 *   1. Entries interleave reverse-chronologically across strength/run/benchmark.
 *   2. Each row's left-border stripe is color-coded by modality.
 *   3. A block divider row appears at a block boundary, reading "Block {N} — {label}".
 *   4. Tapping an entry fires onSelect with that entry.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { TrainingLog } from './TrainingLog'
import type { TrainingLogEntryData, TrainingBlock } from '../../../api/health'

const blocks: TrainingBlock[] = [
  { block_number: 2, label: 'Peak Block', start_date: '2026-07-01', end_date: '2026-07-31' },
  { block_number: 1, label: 'Base Block', start_date: '2026-06-01', end_date: '2026-06-30' },
]

const strengthEntry: TrainingLogEntryData = {
  modality: 'strength',
  date: '2026-07-05',
  workout_id: 'w1',
  title: 'Upper Body A',
  exercises: [
    { name: 'Bench Press', sets: [], set_count: 3, top_set: null, est_1rm: null, volume_kg: 1200 },
  ],
  total_volume_kg: 1200,
}

const runEntry: TrainingLogEntryData = {
  modality: 'run',
  date: '2026-07-03',
  activity_id: 'a1',
  type: 'Easy Run',
  distance_m: 5200,
  avg_pace_sec_per_km: 330,
}

const benchmarkEntry: TrainingLogEntryData = {
  modality: 'benchmark',
  date: '2026-06-20',
  facet: '5K Time Trial',
  value: 1200,
  unit: 'sec',
  previous_value: 1250,
}

describe('TrainingLog', () => {
  it('renders entries reverse-chronologically, interleaving modalities', () => {
    render(
      <TrainingLog entries={[benchmarkEntry, strengthEntry, runEntry]} blocks={blocks} onSelect={() => {}} />,
    )
    const titles = screen
      .getAllByText(/Upper Body A|Easy Run|5K Time Trial/)
      .map((el) => el.textContent)
    expect(titles).toEqual(['Upper Body A', 'Easy Run', '5K Time Trial'])
  })

  it("color-codes each row's left-border stripe by modality", () => {
    render(
      <TrainingLog entries={[strengthEntry, runEntry, benchmarkEntry]} blocks={blocks} onSelect={() => {}} />,
    )
    const strengthRow = screen.getByText('Upper Body A').closest('button')
    const runRow = screen.getByText('Easy Run').closest('button')
    const benchmarkRow = screen.getByText('5K Time Trial').closest('button')
    expect(strengthRow).toHaveStyle('border-left-color: #FB923C')
    expect(runRow).toHaveStyle('border-left-color: #38BDF8')
    expect(benchmarkRow).toHaveStyle('border-left-color: #A78BFA')
  })

  it('renders a block divider at a block boundary', () => {
    render(
      <TrainingLog entries={[strengthEntry, runEntry, benchmarkEntry]} blocks={blocks} onSelect={() => {}} />,
    )
    expect(screen.getByText('Block 1 — Base Block')).toBeInTheDocument()
  })

  it('fires onSelect when an entry is tapped', () => {
    const onSelect = vi.fn()
    render(<TrainingLog entries={[strengthEntry]} blocks={blocks} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Upper Body A'))
    expect(onSelect).toHaveBeenCalledWith(strengthEntry)
  })

  it('renders the empty-state copy when there are no entries', () => {
    render(<TrainingLog entries={[]} blocks={blocks} onSelect={() => {}} />)
    expect(screen.getByText('No training logged in this range.')).toBeInTheDocument()
  })
})
