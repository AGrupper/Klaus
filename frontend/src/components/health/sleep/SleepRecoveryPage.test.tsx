/**
 * SleepRecoveryPage.test.tsx — pipeline-not-live guard vs. per-chart empty
 * state (D-06-style guard, distinct states per 30-UI-SPEC).
 *
 * Locks the single highest-value contract in this plan: `pipeline_active:
 * false` (the biometric-sync cron has NEVER populated a row) must render the
 * "isn't syncing yet" placeholder INSTEAD of the header stats + charts —
 * never the normal per-chart empty state, which is reserved for
 * `pipeline_active: true` with zero rows in the selected range. The two
 * states must be visibly distinct.
 *
 * useSleepRecovery() is mocked so the component renders deterministically
 * without a QueryClient or network — mirrors TimelineDay.test.tsx's
 * useToday() mocking convention.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import type { SleepRecoveryData } from '../../../api/health'

vi.mock('../../../hooks/useHealth', () => ({
  useSleepRecovery: vi.fn(),
}))

import { useSleepRecovery } from '../../../hooks/useHealth'
import { SleepRecoveryPage } from './SleepRecoveryPage'

const mockUseSleepRecovery = vi.mocked(useSleepRecovery)

function setSleepRecovery(partial: Partial<ReturnType<typeof useSleepRecovery>>) {
  mockUseSleepRecovery.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    ...partial,
  } as unknown as ReturnType<typeof useSleepRecovery>)
}

const emptySeries = { x: 'unused', y: null } // placeholder shape reference only

function emptyRangeData(pipelineActive: boolean): SleepRecoveryData {
  return {
    range: '30d',
    series: {
      hrv_overnight: [],
      sleep_score: [],
      sleep_duration: [],
      body_battery_max: [],
      hrv_baseline: [],
    },
    header_stats: null,
    pipeline_active: pipelineActive,
  }
}

describe('SleepRecoveryPage — pipeline-not-live guard (D-06-style, D-19)', () => {
  beforeEach(() => {
    mockUseSleepRecovery.mockReset()
    void emptySeries
  })

  it('renders a loading state while the initial fetch is in-flight', () => {
    setSleepRecovery({ isLoading: true })
    render(<SleepRecoveryPage />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('renders the error copy on fetch failure', () => {
    setSleepRecovery({ isError: true, error: new Error('boom') })
    render(<SleepRecoveryPage />)
    expect(
      screen.getByText("Couldn't load sleep & recovery data — pull to refresh."),
    ).toBeInTheDocument()
  })

  it('pipeline_active=false: renders the "isn\'t syncing yet" placeholder and NOT the charts', () => {
    setSleepRecovery({ data: emptyRangeData(false) })
    render(<SleepRecoveryPage />)
    expect(
      screen.getByText("Sleep & recovery data isn't syncing yet."),
    ).toBeInTheDocument()
    // The distinct per-chart empty states must NOT appear alongside the
    // pipeline-not-live placeholder.
    expect(screen.queryByText('No HRV data for this range.')).not.toBeInTheDocument()
    expect(screen.queryByText('No sleep data for this range.')).not.toBeInTheDocument()
    expect(
      screen.queryByText('No body battery data for this range.'),
    ).not.toBeInTheDocument()
    // Chart headings themselves must not render either — no empty-axes charts.
    expect(screen.queryByText('HRV')).not.toBeInTheDocument()
    expect(screen.queryByText('Body Battery')).not.toBeInTheDocument()
  })

  it('pipeline_active=true with an empty range: renders the charts with their per-chart empty states (distinct from the pipeline-not-live placeholder)', () => {
    setSleepRecovery({ data: emptyRangeData(true) })
    render(<SleepRecoveryPage />)
    expect(
      screen.queryByText("Sleep & recovery data isn't syncing yet."),
    ).not.toBeInTheDocument()
    expect(screen.getByText('No HRV data for this range.')).toBeInTheDocument()
    expect(screen.getByText('No sleep data for this range.')).toBeInTheDocument()
    expect(screen.getByText('No body battery data for this range.')).toBeInTheDocument()
    // Chart card headings render (the charts exist, just empty)
    expect(screen.getByText('HRV')).toBeInTheDocument()
    expect(screen.getByText('Sleep')).toBeInTheDocument()
    expect(screen.getByText('Body Battery')).toBeInTheDocument()
  })

  it('renders header stats + all three charts wired when pipeline_active=true with real data', () => {
    const fullData: SleepRecoveryData = {
      range: '30d',
      series: {
        hrv_overnight: [{ x: '2026-07-01', y: 65 }],
        sleep_score: [{ x: '2026-07-01', y: 82 }],
        sleep_duration: [{ x: '2026-07-01', y: 7.5 }],
        body_battery_max: [{ x: '2026-07-01', y: 90 }],
        hrv_baseline: [{ x: '2026-07-01', y: 60 }],
      },
      header_stats: {
        date: '2026-07-01',
        hrv_overnight: 65,
        sleep_score: 82,
        body_battery_max: 90,
        resting_hr: 52,
        training_readiness: 75,
      },
      pipeline_active: true,
    }
    setSleepRecovery({ data: fullData })
    render(<SleepRecoveryPage />)
    expect(screen.getAllByText('65 ms').length).toBeGreaterThan(0)
    expect(screen.getByText('HRV')).toBeInTheDocument()
    expect(screen.getByText('Sleep')).toBeInTheDocument()
    expect(screen.getByText('Body Battery')).toBeInTheDocument()
  })
})
