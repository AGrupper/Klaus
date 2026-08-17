/**
 * useTapGuard — only a deliberate, stationary tap may fire an action.
 *
 * The bug (Amit's UAT, twice): pulling the page down with a thumb on a header
 * button opened that button's sheet. iOS still emits a `click` on release
 * after a drag, and two earlier attempts at *detecting* the drag both leaked:
 *
 *   - watching `pointermove` failed because iOS stops sending pointer moves
 *     once the scroller claims the gesture,
 *   - watching `touchmove` failed because a claimed gesture can end in
 *     `touchcancel` with no move ever reported — leaving the fallback click
 *     path to fire the action.
 *
 * So this no longer tries to classify the gesture from movement alone. On any
 * device that has produced a touch, `click` is permanently distrusted and the
 * ONLY thing that fires the action is a `touchend` that both stayed within a
 * few pixels and was never cancelled. Mouse and keyboard input still go
 * through `click`, because such devices never set the touch flag.
 *
 * A third leak survived even that: if the browser never routes the gesture
 * through the button at all and simply emits a stray click, there is nothing
 * local to inspect. So the final authority is `recentlyScrolled()` — a global
 * latch fed by scroll/touchmove anywhere in the app. Any activation landing
 * within ~450ms of page movement is spill-over, whatever its shape.
 *
 * Usage:
 *   const guard = useTapGuard(onPress)
 *   <button {...guard}>…</button>
 */
import { useCallback, useRef } from 'react'
import { recentlyScrolled } from '../utils/scrollLatch'

/** Finger travel beyond this is a scroll gesture, not a tap. */
const MOVE_TOLERANCE_PX = 10

/**
 * Set the first time any touch is seen anywhere in the app. Module-level on
 * purpose: once we know this is a touch device, every guarded button should
 * distrust synthetic clicks, including ones mounted later.
 */
let sawTouch = false

export function useTapGuard(onPress: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null)
  const disqualified = useRef(false)

  const onTouchStart = useCallback((event: React.TouchEvent) => {
    sawTouch = true
    const touch = event.touches[0]
    start.current = touch ? { x: touch.clientX, y: touch.clientY } : null
    disqualified.current = false
  }, [])

  const onTouchMove = useCallback((event: React.TouchEvent) => {
    const touch = event.touches[0]
    if (!touch || !start.current) return
    if (
      Math.abs(touch.clientX - start.current.x) > MOVE_TOLERANCE_PX ||
      Math.abs(touch.clientY - start.current.y) > MOVE_TOLERANCE_PX
    ) {
      disqualified.current = true
    }
  }, [])

  /** The system took the gesture (scroll, swipe-back, notification pull). */
  const onTouchCancel = useCallback(() => {
    disqualified.current = true
    start.current = null
  }, [])

  /** Belt and braces: a pointer cancel means the same thing. */
  const onPointerCancel = useCallback(() => {
    disqualified.current = true
  }, [])

  const onTouchEnd = useCallback(
    (event: React.TouchEvent) => {
      const began = start.current
      const wasDisqualified = disqualified.current
      start.current = null
      disqualified.current = false
      if (!began || wasDisqualified) return

      // Release point must also be near the start — touchmove can be starved
      // on a fast flick, so check the final position directly.
      const touch = event.changedTouches?.[0]
      if (
        touch &&
        (Math.abs(touch.clientX - began.x) > MOVE_TOLERANCE_PX ||
          Math.abs(touch.clientY - began.y) > MOVE_TOLERANCE_PX)
      ) {
        return
      }

      // Final gate: the page must have been still.
      if (recentlyScrolled()) return

      if (event.cancelable) event.preventDefault()
      onPress()
    },
    [onPress],
  )

  const onClick = useCallback(() => {
    // On a touch device the decision was already made in touchend; a click
    // arriving here is the synthetic one iOS emits after any gesture.
    if (sawTouch) return
    // Desktop still needs the latch: a trackpad flick can land a click too.
    if (recentlyScrolled()) return
    onPress()
  }, [onPress])

  return {
    onTouchStart,
    onTouchMove,
    onTouchEnd,
    onTouchCancel,
    onPointerCancel,
    onClick,
  }
}

/** Test-only: reset the module-level touch-device latch. */
export function __resetTapGuardForTests(): void {
  sawTouch = false
}
