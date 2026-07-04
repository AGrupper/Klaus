/**
 * useAppBadge.test.ts — Tests for the icon-badge reconciliation hook (D-18).
 *
 * navigator.setAppBadge/clearAppBadge and serviceWorker.controller.postMessage
 * are mocked as minimal stand-ins; jsdom does not implement the Badging API.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useAppBadge } from './useAppBadge'

describe('useAppBadge', () => {
  let setAppBadge: ReturnType<typeof vi.fn>
  let clearAppBadge: ReturnType<typeof vi.fn>
  let postMessage: ReturnType<typeof vi.fn>

  beforeEach(() => {
    setAppBadge = vi.fn().mockResolvedValue(undefined)
    clearAppBadge = vi.fn().mockResolvedValue(undefined)
    postMessage = vi.fn()

    Object.defineProperty(navigator, 'setAppBadge', {
      value: setAppBadge,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(navigator, 'clearAppBadge', {
      value: clearAppBadge,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { controller: { postMessage } },
      configurable: true,
      writable: true,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    // @ts-expect-error — cleanup test-only shims
    delete navigator.setAppBadge
    // @ts-expect-error — cleanup test-only shims
    delete navigator.clearAppBadge
    // @ts-expect-error — cleanup test-only shims
    delete navigator.serviceWorker
  })

  it('calls setAppBadge and posts RESET_BADGE when unreadCount > 0', () => {
    renderHook(() => useAppBadge(3))

    expect(setAppBadge).toHaveBeenCalledWith(3)
    expect(clearAppBadge).not.toHaveBeenCalled()
    expect(postMessage).toHaveBeenCalledWith({ type: 'RESET_BADGE', count: 3 })
  })

  it('calls clearAppBadge and posts RESET_BADGE with count 0 when unreadCount is 0', () => {
    renderHook(() => useAppBadge(0))

    expect(clearAppBadge).toHaveBeenCalledTimes(1)
    expect(setAppBadge).not.toHaveBeenCalled()
    expect(postMessage).toHaveBeenCalledWith({ type: 'RESET_BADGE', count: 0 })
  })

  it('re-reconciles when unreadCount changes across renders', () => {
    const { rerender } = renderHook(({ count }) => useAppBadge(count), {
      initialProps: { count: 2 },
    })
    expect(setAppBadge).toHaveBeenCalledWith(2)

    rerender({ count: 0 })
    expect(clearAppBadge).toHaveBeenCalledTimes(1)
  })

  it('does not throw when setAppBadge is unavailable', () => {
    // @ts-expect-error — simulate an unsupported browser
    delete navigator.setAppBadge
    // @ts-expect-error
    delete navigator.clearAppBadge

    expect(() => renderHook(() => useAppBadge(5))).not.toThrow()
    expect(postMessage).not.toHaveBeenCalled()
  })
})
