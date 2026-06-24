/**
 * useVisualViewport.test.ts — Tests for the keyboard-inset hook.
 *
 * Covers the iOS soft-keyboard inset calculation used to anchor phone bottom
 * sheets above the keyboard. window.visualViewport is mocked as a minimal
 * event target so the resize/scroll listeners can be driven synchronously.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useVisualViewport } from './useVisualViewport'

// ---------------------------------------------------------------------------
// Minimal visualViewport mock
// ---------------------------------------------------------------------------

interface MockVV {
  height: number
  offsetTop: number
  listeners: Record<string, Array<() => void>>
  addEventListener: (t: string, cb: () => void) => void
  removeEventListener: (t: string, cb: () => void) => void
  emit: (t: string) => void
}

function makeMockVV(height: number, offsetTop = 0): MockVV {
  const listeners: Record<string, Array<() => void>> = {}
  return {
    height,
    offsetTop,
    listeners,
    addEventListener(t, cb) {
      ;(listeners[t] ??= []).push(cb)
    },
    removeEventListener(t, cb) {
      listeners[t] = (listeners[t] ?? []).filter((f) => f !== cb)
    },
    emit(t) {
      ;(listeners[t] ?? []).forEach((f) => f())
    },
  }
}

const ORIGINAL_VV = window.visualViewport
const ORIGINAL_INNER_HEIGHT = window.innerHeight

function setInnerHeight(h: number) {
  Object.defineProperty(window, 'innerHeight', { value: h, configurable: true, writable: true })
}

function setVV(vv: MockVV | null) {
  Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true, writable: true })
}

describe('useVisualViewport', () => {
  beforeEach(() => {
    setInnerHeight(800)
  })

  afterEach(() => {
    setVV(ORIGINAL_VV as unknown as MockVV | null)
    setInnerHeight(ORIGINAL_INNER_HEIGHT)
    vi.clearAllMocks()
  })

  // Case 1: no keyboard → inset 0 (visual viewport fills the layout viewport)
  it('returns 0 when the visual viewport equals the layout viewport', () => {
    setVV(makeMockVV(800, 0))
    const { result } = renderHook(() => useVisualViewport())
    expect(result.current.keyboardInset).toBe(0)
  })

  // Case 2: keyboard open → inset equals the covered height
  it('returns the keyboard height when the visual viewport shrinks', () => {
    const vv = makeMockVV(800, 0)
    setVV(vv)
    const { result } = renderHook(() => useVisualViewport())

    act(() => {
      vv.height = 500 // keyboard takes 300px
      vv.emit('resize')
    })

    expect(result.current.keyboardInset).toBe(300)
  })

  // Case 3: offsetTop is subtracted (page panned up under the keyboard)
  it('subtracts visualViewport.offsetTop', () => {
    const vv = makeMockVV(500, 40)
    setVV(vv)
    const { result } = renderHook(() => useVisualViewport())
    // 800 - 500 - 40 = 260
    expect(result.current.keyboardInset).toBe(260)
  })

  // Case 4: sub-pixel noise is clamped to 0 (no jitter without a keyboard)
  it('clamps sub-pixel deltas to 0', () => {
    setVV(makeMockVV(799.4, 0))
    const { result } = renderHook(() => useVisualViewport())
    expect(result.current.keyboardInset).toBe(0)
  })

  // Case 5: graceful when visualViewport is unavailable (old Safari / SSR)
  it('returns 0 when window.visualViewport is undefined', () => {
    setVV(null)
    const { result } = renderHook(() => useVisualViewport())
    expect(result.current.keyboardInset).toBe(0)
  })

  // Case 6: listeners are removed on unmount
  it('removes resize/scroll listeners on unmount', () => {
    const vv = makeMockVV(800, 0)
    setVV(vv)
    const { unmount } = renderHook(() => useVisualViewport())
    expect(vv.listeners['resize']?.length).toBe(1)
    expect(vv.listeners['scroll']?.length).toBe(1)
    unmount()
    expect(vv.listeners['resize']?.length).toBe(0)
    expect(vv.listeners['scroll']?.length).toBe(0)
  })
})
