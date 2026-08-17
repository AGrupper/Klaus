/**
 * useTapGuard — the pull-to-refresh bug from Amit's UAT: dragging the page
 * down with a thumb on a header button still fired that button's click, so
 * every pull opened the Customize sheet.
 *
 * Driven through the hook's handlers rather than fireEvent: jsdom has no
 * PointerEvent or TouchEvent, so synthesised events arrive without
 * coordinates and every gesture would look stationary.
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useTapGuard } from './useTapGuard'

type Handlers = ReturnType<typeof useTapGuard>

function touch(x: number, y: number) {
  return { touches: [{ clientX: x, clientY: y }] } as unknown as React.TouchEvent
}

function touchEnd() {
  return { cancelable: true, preventDefault: vi.fn() } as unknown as React.TouchEvent
}

/** A finger gesture: down → move → up, then iOS's trailing synthetic click. */
function fingerGesture(h: Handlers, from: [number, number], to: [number, number]) {
  act(() => {
    h.onTouchStart(touch(from[0], from[1]))
    h.onTouchMove(touch(to[0], to[1]))
    h.onTouchEnd(touchEnd())
    h.onClick()
  })
}

/** A mouse gesture — no touch events fire at all. */
function mouseGesture(h: Handlers, from: [number, number], to: [number, number]) {
  act(() => {
    h.onPointerDown({
      pointerType: 'mouse', clientX: from[0], clientY: from[1],
    } as React.PointerEvent)
    h.onPointerMove({
      pointerType: 'mouse', clientX: to[0], clientY: to[1],
    } as React.PointerEvent)
    h.onClick()
  })
}

describe('useTapGuard', () => {
  it('fires once on a stationary tap', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    fingerGesture(result.current, [100, 40], [100, 40])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('tolerates a few pixels of finger wobble', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    fingerGesture(result.current, [100, 40], [104, 46])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('swallows the gesture when the finger dragged down (pull-to-refresh)', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    fingerGesture(result.current, [100, 40], [104, 190])
    expect(onPress).not.toHaveBeenCalled()
  })

  it('swallows a horizontal swipe too', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    fingerGesture(result.current, [100, 40], [260, 44])
    expect(onPress).not.toHaveBeenCalled()
  })

  it('treats pointercancel as a scroll — iOS stops sending moves once the scroller takes over', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    act(() => {
      result.current.onTouchStart(touch(100, 40))
      result.current.onPointerCancel()
      result.current.onTouchEnd(touchEnd())
      result.current.onClick()
    })
    expect(onPress).not.toHaveBeenCalled()
  })

  it('recovers: a drag then a clean tap still fires once', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    fingerGesture(result.current, [100, 40], [100, 200])
    expect(onPress).not.toHaveBeenCalled()
    fingerGesture(result.current, [100, 40], [100, 41])
    expect(onPress).toHaveBeenCalledTimes(1)
  })

  it('still works for mouse input, where touch events never fire', () => {
    const onPress = vi.fn()
    const { result } = renderHook(() => useTapGuard(onPress))
    mouseGesture(result.current, [100, 40], [101, 41])
    expect(onPress).toHaveBeenCalledTimes(1)
    mouseGesture(result.current, [100, 40], [100, 300])
    expect(onPress).toHaveBeenCalledTimes(1) // the drag was ignored
  })
})
