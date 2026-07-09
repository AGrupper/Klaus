/**
 * HealthPage.test.tsx — sub-tab → sub-page switch contract (30-08).
 *
 * Locks: HealthPage renders the Training sub-page by default (no localStorage
 * key), restores the persisted sub-page when localStorage['health-tab'] is
 * set, and swaps the rendered sub-page when the tab changes — without a route
 * change. The three sub-pages are mocked to simple markers so this test
 * targets only the switch logic (each real sub-page owns its own react-query /
 * chart tests).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'

vi.mock('./training/TrainingHistoryPage', () => ({
  TrainingHistoryPage: () => <div data-testid="training-page">Training</div>,
}))
vi.mock('./nutrition/NutritionDetailPage', () => ({
  NutritionDetailPage: () => <div data-testid="nutrition-page">Nutrition</div>,
}))
vi.mock('./sleep/SleepRecoveryPage', () => ({
  SleepRecoveryPage: () => <div data-testid="sleep-page">Sleep</div>,
}))

import { HealthPage } from './HealthPage'

describe('HealthPage — sub-tab → sub-page switch (HLTH-01/02/03)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders the Training sub-page by default when no tab is persisted', () => {
    render(<HealthPage />)
    expect(screen.getByTestId('training-page')).toBeInTheDocument()
    expect(screen.queryByTestId('nutrition-page')).not.toBeInTheDocument()
    expect(screen.queryByTestId('sleep-page')).not.toBeInTheDocument()
  })

  it('restores the persisted sub-page from localStorage on mount', () => {
    localStorage.setItem('health-tab', 'sleep')
    render(<HealthPage />)
    expect(screen.getByTestId('sleep-page')).toBeInTheDocument()
    expect(screen.queryByTestId('training-page')).not.toBeInTheDocument()
  })

  it('swaps the rendered sub-page when the tab changes (no route change)', () => {
    render(<HealthPage />)
    expect(screen.getByTestId('training-page')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Nutrition' }))
    expect(screen.getByTestId('nutrition-page')).toBeInTheDocument()
    expect(screen.queryByTestId('training-page')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Sleep' }))
    expect(screen.getByTestId('sleep-page')).toBeInTheDocument()
    expect(screen.queryByTestId('nutrition-page')).not.toBeInTheDocument()
  })
})
