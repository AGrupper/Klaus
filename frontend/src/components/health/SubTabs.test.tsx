/**
 * SubTabs.test.tsx — localStorage persistence contract (D-01, D-02).
 *
 * Locks: default tab is 'training' when no localStorage key exists, a
 * previously-persisted tab is restored on mount, and every tab change writes
 * the new value back to localStorage['health-tab'].
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { SubTabs } from './SubTabs'

describe('SubTabs — persisted 3-way tab (D-01, D-02)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to Training when no localStorage key is set', () => {
    render(<SubTabs />)
    expect(screen.getByRole('button', { name: 'Training' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Nutrition' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Sleep' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(localStorage.getItem('health-tab')).toBeNull()
  })

  it('restores the persisted tab from localStorage on mount', () => {
    localStorage.setItem('health-tab', 'sleep')
    render(<SubTabs />)
    expect(screen.getByRole('button', { name: 'Sleep' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Training' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('writes the selected tab to localStorage on every change', () => {
    render(<SubTabs />)
    fireEvent.click(screen.getByRole('button', { name: 'Nutrition' }))
    expect(localStorage.getItem('health-tab')).toBe('nutrition')
    expect(screen.getByRole('button', { name: 'Nutrition' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Sleep' }))
    expect(localStorage.getItem('health-tab')).toBe('sleep')
    expect(screen.getByRole('button', { name: 'Sleep' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('calls onChange with the active tab on mount and on every change', () => {
    const seen: string[] = []
    render(<SubTabs onChange={(tab) => seen.push(tab)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Nutrition' }))
    expect(seen).toEqual(['training', 'nutrition'])
  })
})
