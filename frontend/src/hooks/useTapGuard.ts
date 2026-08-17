/**
 * useTapGuard — ignore "taps" that were really a drag.
 *
 * iOS fires a click on release even when the finger travelled, so pulling the
 * page down with a thumb resting on a header button opened that button's
 * sheet (Amit's UAT: "every time I pull down it tries to open the
 * customization tab"). This records where the pointer went down and swallows
 * the click if it moved beyond a small threshold.
 *
 * Usage:
 *   const guard = useTapGuard(onPress)
 *   <button {...guard}>…</button>
 */
import { useCallback, useRef } from 'react'

/** Finger travel beyond this is a scroll gesture, not a tap. */
const MOVE_TOLERANCE_PX = 10

export function useTapGuard(onPress: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null)
  const moved = useRef(false)

  const onPointerDown = useCallback((event: React.PointerEvent) => {
    start.current = { x: event.clientX, y: event.clientY }
    moved.current = false
  }, [])

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    if (!start.current) return
    const dx = Math.abs(event.clientX - start.current.x)
    const dy = Math.abs(event.clientY - start.current.y)
    if (dx > MOVE_TOLERANCE_PX || dy > MOVE_TOLERANCE_PX) moved.current = true
  }, [])

  const onClick = useCallback(() => {
    if (moved.current) {
      moved.current = false
      return
    }
    onPress()
  }, [onPress])

  return { onPointerDown, onPointerMove, onClick }
}
