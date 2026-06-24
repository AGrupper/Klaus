/**
 * useVisualViewport.ts — Reactive on-screen-keyboard inset for fixed bottom sheets.
 *
 * On iOS Safari a `position:fixed; bottom:0` element is anchored to the *layout*
 * viewport, which does NOT shrink when the soft keyboard opens. The keyboard
 * therefore covers the bottom of any fixed bottom sheet, and iOS pans the layout
 * to bring the focused field into view (which shows up as a horizontal shift).
 *
 * `window.visualViewport` reports the *visual* viewport (the area actually visible
 * above the keyboard). The keyboard height is the gap between the layout viewport
 * bottom and the visual viewport bottom:
 *
 *   keyboardInset = layoutViewportHeight - visualViewport.height - visualViewport.offsetTop
 *
 * Bottom sheets set `bottom: keyboardInset` so they ride directly above the
 * keyboard. With no keyboard the inset is 0 ⇒ `bottom: 0` (unchanged behaviour).
 *
 * Guard: returns 0 when `window.visualViewport` is unavailable (SSR / old Safari).
 */
import { useEffect, useState } from 'react'

function readKeyboardInset(): number {
  if (typeof window === 'undefined' || !window.visualViewport) return 0
  const vv = window.visualViewport
  const inset = window.innerHeight - vv.height - vv.offsetTop
  // Small sub-pixel deltas show up even with no keyboard; clamp to >= 0 and
  // ignore noise below a few pixels so the sheet doesn't jitter.
  return inset > 1 ? Math.round(inset) : 0
}

export function useVisualViewport(): { keyboardInset: number } {
  const [keyboardInset, setKeyboardInset] = useState<number>(() => readKeyboardInset())

  useEffect(() => {
    const vv = typeof window !== 'undefined' ? window.visualViewport : null
    if (!vv) return

    function handleChange() {
      setKeyboardInset(readKeyboardInset())
    }

    vv.addEventListener('resize', handleChange)
    vv.addEventListener('scroll', handleChange)
    // Sync once on mount in case the keyboard is already open.
    handleChange()

    return () => {
      vv.removeEventListener('resize', handleChange)
      vv.removeEventListener('scroll', handleChange)
    }
  }, [])

  return { keyboardInset }
}
