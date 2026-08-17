/**
 * useTapGuard — ignore "taps" that were really a scroll gesture.
 *
 * iOS fires a click on release even when the finger travelled, so pulling the
 * page down with a thumb resting on a header button opened that button's
 * sheet (Amit's UAT: "every time I pull down it tries to open the
 * customization tab").
 *
 * The first attempt watched pointer events alone and still let it through:
 * when iOS hands a gesture to the scroller it stops sending pointermove and
 * fires pointercancel instead, so nothing ever marked the gesture as moved.
 * This version watches three signals:
 *
 *   1. touchmove — the reliable one on iOS; touch events keep targeting the
 *      original element for the whole gesture,
 *   2. pointercancel — iOS's "the scroller has taken over" signal,
 *   3. pointermove — desktop/pen, where touch events never fire.
 *
 * A clean tap is handled in touchend (with preventDefault so the synthetic
 * click can't fire it twice); mouse input still goes through onClick.
 *
 * Usage:
 *   const guard = useTapGuard(onPress)
 *   <button {...guard}>…</button>
 */
import { useCallback, useRef } from 'react'

/** Finger travel beyond this is a scroll gesture, not a tap. */
const MOVE_TOLERANCE_PX = 10
/** How long a touch-handled press suppresses the trailing synthetic click. */
const CLICK_SUPPRESS_MS = 500

export function useTapGuard(onPress: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null)
  const moved = useRef(false)
  const handledByTouch = useRef(false)

  const begin = useCallback((x: number, y: number) => {
    start.current = { x, y }
    moved.current = false
  }, [])

  const track = useCallback((x: number, y: number) => {
    if (!start.current) return
    if (
      Math.abs(x - start.current.x) > MOVE_TOLERANCE_PX ||
      Math.abs(y - start.current.y) > MOVE_TOLERANCE_PX
    ) {
      moved.current = true
    }
  }, [])

  const onTouchStart = useCallback(
    (event: React.TouchEvent) => {
      const touch = event.touches[0]
      if (touch) begin(touch.clientX, touch.clientY)
    },
    [begin],
  )

  const onTouchMove = useCallback(
    (event: React.TouchEvent) => {
      const touch = event.touches[0]
      if (touch) track(touch.clientX, touch.clientY)
    },
    [track],
  )

  const onTouchEnd = useCallback(
    (event: React.TouchEvent) => {
      handledByTouch.current = true
      window.setTimeout(() => {
        handledByTouch.current = false
      }, CLICK_SUPPRESS_MS)
      if (moved.current) {
        moved.current = false
        return
      }
      // Consume the gesture here so the trailing synthetic click is a no-op.
      if (event.cancelable) event.preventDefault()
      onPress()
    },
    [onPress],
  )

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (event.pointerType === 'touch') return // touch handlers own this
      begin(event.clientX, event.clientY)
    },
    [begin],
  )

  const onPointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (event.pointerType === 'touch') return
      track(event.clientX, event.clientY)
    },
    [track],
  )

  /** iOS fires this the moment the scroller claims the gesture. */
  const onPointerCancel = useCallback(() => {
    moved.current = true
  }, [])

  const onClick = useCallback(() => {
    if (handledByTouch.current) return // already handled in touchend
    if (moved.current) {
      moved.current = false
      return
    }
    onPress()
  }, [onPress])

  return {
    onTouchStart,
    onTouchMove,
    onTouchEnd,
    onPointerDown,
    onPointerMove,
    onPointerCancel,
    onClick,
  }
}
