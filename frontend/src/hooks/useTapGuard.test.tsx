/**
 * useTapGuard — the pull-to-refresh bug from Amit's UAT: dragging the page
 * down with a thumb on a header button still fired that button's click, so
 * every pull opened the Customize sheet.
 *
 * Driven through the hook's handlers rather than fireEvent: jsdom has no
 * PointerEvent, so synthesised pointer events arrive without coordinates and
 * every gesture would look stationary.
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useTapGuard } from './useTapGuard'

type Handlers = ReturnType<typeof useTapGuard>

function gesture(handlers: Handlers, from: [number, number], to: [number, number]) {
  act(() => {
    handlers.onPointerDown({ clientX: from[0], clientY: from[1] } as React.PointerEvent)
    handlers.onPointerMove({ clientX: to[0], clientY: to[1] } as React.PointerEvent)
    handlers.onClick()
  })
}

describe('useTapGuard', () => {
  it('fires on a stationary tap', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    gesture(result.current, [100, 40], [100, 40])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('tolerates a few pixels of finger wobble', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    gesture(result.current, [100, 40], [104, 46])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('swallows the click when the finger dragged down (pull-to-refresh)', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    gesture(result.current, [100, 40], [104, 190])
    expect(onPress).not.toHaveBeenCalled()
  })

  it('swallows a horizontal swipe too', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    gesture(result.current, [100, 40], [260, 44])
    expect(onPress).not.toHaveBeenCalled()
  })

  it('recovers: a drag then a clean tap still fires once', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    gesture(result.current, [100, 40], [100, 200])
    expect(onPress).not.toHaveBeenCalled()
    gesture(result.current, [100, 40], [100, 41])
    expect(onPress).toHaveBeenCalledTimes(1)
  })
})
