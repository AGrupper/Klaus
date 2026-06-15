/**
 * TimelineDay.test.tsx — Vitest spec for the Today timeline (plan 26-07).
 *
 * Covers the must_haves that are unit-testable in jsdom:
 *   - loading → shimmer skeletons (HUB-03), error → role="alert"
 *   - calendar renders chronologically with all-day events pinned (TIME-01)
 *   - meals render as slot labels with macros, never as eating times (TIME-03)
 *   - training shows "Week N of 16" block context (TIME-04)
 *   - coach note renders, and a D-06 placeholder shows when it is null
 *
 * useToday() is mocked so the component renders deterministically without a
 * QueryClient or network. NowLine calls scrollIntoView on mount, which jsdom
 * does not implement — it is stubbed below.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import type { TodayData } from '../../api/today'

vi.mock('../../hooks/useToday', () => ({
  TODAY_QUERY_KEY: ['today'],
  useToday: vi.fn(),
  useRefreshToday: () => () => {},
}))

import { useToday } from '../../hooks/useToday'
import { TimelineDay } from './TimelineDay'

const mockUseToday = vi.mocked(useToday)

// jsdom does not implement scrollIntoView (called by NowLine on mount).
window.HTMLElement.prototype.scrollIntoView = vi.fn()

function setToday(partial: Partial<ReturnType<typeof useToday>>) {
  mockUseToday.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    ...partial,
  } as unknown as ReturnType<typeof useToday>)
}

const fullData: TodayData = {
  today: '2026-06-15',
  calendar: {
    all_day: ['Sprint review'],
    timed: [
      { id: '1', title: 'Morning standup', start: '2026-06-15T09:00:00+03:00', end: '2026-06-15T09:15:00+03:00' },
      { id: '2', title: 'Evening gym', start: '2026-06-15T18:00:00+03:00', end: '2026-06-15T19:15:00+03:00' },
    ],
  },
  garmin: { sleep: 7.5, hrv: 65, body_battery: 80, resting_hr: 52 },
  weather: 'Sunny, 28°C',
  meals: [
    { slot_label: 'Breakfast', macros: { kcal: 500, protein_g: 30, carbs_g: 50, fat_g: 15, fiber_g: 8 } },
  ],
  training: { item: 'Lower Body A', block_context: 'Week 3 of 16 — Lower Body A' },
  coach_note: 'Easy run today — HRV is solid.',
  nutrition_totals: { kcal: 500, protein_g: 30, carbs_g: 50, fat_g: 15, fiber_g: 8 },
}

describe('TimelineDay', () => {
  beforeEach(() => {
    mockUseToday.mockReset()
  })

  it('renders a loading state while the initial fetch is in-flight (HUB-03)', () => {
    setToday({ isLoading: true })
    render(<TimelineDay />)
    expect(screen.getByLabelText(/Loading today/i)).toBeInTheDocument()
  })

  it('renders an alert on error', () => {
    setToday({ isError: true, error: new Error('today fetch failed') })
    render(<TimelineDay />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('today fetch failed')
  })

  it('renders calendar events with the all-day event pinned (TIME-01)', () => {
    setToday({ data: fullData })
    render(<TimelineDay />)
    expect(screen.getByText('Morning standup')).toBeInTheDocument()
    expect(screen.getByText('Evening gym')).toBeInTheDocument()
    // All-day event title is rendered (pinned section)
    expect(screen.getByText('Sprint review')).toBeInTheDocument()
  })

  it('renders meals as slot labels with macros, never as eating times (TIME-03)', () => {
    setToday({ data: fullData })
    render(<TimelineDay />)
    expect(screen.getByText('Breakfast')).toBeInTheDocument()
    // No eating-time wording is ever derived from slot meals (CLAUDE.md invariant)
    expect(screen.queryByText(/eaten at|eating time/i)).not.toBeInTheDocument()
  })

  it('renders the training block context "Week N of 16" (TIME-04)', () => {
    setToday({ data: fullData })
    render(<TimelineDay />)
    expect(screen.getByText(/Week 3 of 16/)).toBeInTheDocument()
  })

  it('renders the coach note when present', () => {
    setToday({ data: fullData })
    render(<TimelineDay />)
    expect(screen.getByText('Easy run today — HRV is solid.')).toBeInTheDocument()
  })

  it('renders the D-06 placeholder when the coach note is not yet available', () => {
    setToday({ data: { ...fullData, coach_note: null } })
    render(<TimelineDay />)
    expect(
      screen.getByText(/Coach note coming after your morning briefing/i),
    ).toBeInTheDocument()
  })
})
