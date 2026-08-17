/**
 * useTapGuard — the pull-to-refresh bug from Amit's UAT: dragging the page
 * down with a thumb on a header button fired that button, opening Customize.
 *
 * Two earlier fixes leaked, so the contract is now strict: once any touch is
 * seen, ONLY a clean touchend fires the action; synthetic clicks never do.
 * These cases cover each way iOS can end a claimed gesture.
 *
 * Driven through the hook's handlers rather than fireEvent: jsdom has no
 * TouchEvent or PointerEvent, so synthesised events carry no coordinates.
 */
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useTapGuard, __resetTapGuardForTests } from './useTapGuard'
import { __setLastMovementForTests } from '../utils/scrollLatch'

type Handlers = ReturnType<typeof useTapGuard>

const touchAt = (x: number, y: number) =>
  ({ touches: [{ clientX: x, clientY: y }] }) as unknown as React.TouchEvent

const endAt = (x: number, y: number) =>
  ({
    changedTouches: [{ clientX: x, clientY: y }],
    cancelable: true,
    preventDefault: vi.fn(),
  }) as unknown as React.TouchEvent

beforeEach(() => {
  __resetTapGuardForTests()
  __setLastMovementForTests(0) // page is still unless a test says otherwise
})

function tap(h: Handlers, from: [number, number], to: [number, number]) {
  act(() => {
    h.onTouchStart(touchAt(from[0], from[1]))
    h.onTouchMove(touchAt(to[0], to[1]))
    h.onTouchEnd(endAt(to[0], to[1]))
    h.onClick() // iOS emits this afterwards regardless
  })
}

describe('useTapGuard', () => {
  it('fires once on a stationary tap', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    tap(result.current, [100, 40], [100, 40])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('tolerates a few pixels of finger wobble', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    tap(result.current, [100, 40], [104, 46])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('ignores a drag reported through touchmove', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    tap(result.current, [100, 40], [104, 190])
    expect(onPress).not.toHaveBeenCalled()
  })

  it('ignores a flick where touchmove never fired — the release point decides', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onTouchStart(touchAt(100, 40))
      result.current.onTouchEnd(endAt(100, 260)) // no move event at all
      result.current.onClick()
    })
    expect(onPress).not.toHaveBeenCalled()
  })

  it('ignores a gesture the system cancelled — the case that kept leaking', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onTouchStart(touchAt(100, 40))
      result.current.onTouchCancel()
      result.current.onClick() // no touchend at all — only the synthetic click
    })
    expect(onPress).not.toHaveBeenCalled()
  })

  it('ignores a pointercancel gesture too', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onTouchStart(touchAt(100, 40))
      result.current.onPointerCancel()
      result.current.onTouchEnd(endAt(100, 42))
      result.current.onClick()
    })
    expect(onPress).not.toHaveBeenCalled()
  })

  it('recovers: a cancelled gesture then a clean tap still fires once', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onTouchStart(touchAt(100, 40))
      result.current.onTouchCancel()
      result.current.onClick()
    })
    expect(onPress).not.toHaveBeenCalled()
    tap(result.current, [100, 40], [100, 41])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('a bare click on a touch device never fires the action', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    // Establish the device as touch-capable, then send a lone click.
    tap(result.current, [10, 10], [10, 10])
    onPress.mockClear()
    act(() => {
      result.current.onClick()
    })
    expect(onPress).not.toHaveBeenCalled()
  })

  it('ignores a tap that lands right after the page scrolled — the leak that survived three fixes', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    __setLastMovementForTests(Date.now())
    tap(result.current, [100, 40], [100, 40]) // looks stationary, but the page just moved
    expect(onPress).not.toHaveBeenCalled()
  })

  it('still works for mouse input, where touch events never fire', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onClick()
    })
    expect(onPress).toHaveBeenCalledTimes(1)
  })
})
