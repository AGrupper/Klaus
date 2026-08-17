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

/** True only while a text field is focused — i.e. a keyboard can exist. */
function keyboardCouldBeOpen(): boolean {
  const active = document.activeElement
  if (!active) return false
  const tag = active.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    (active as HTMLElement).isContentEditable === true
  )
}

function readKeyboardInset(): number {
  if (typeof window === 'undefined' || !window.visualViewport) return 0

  // Guard against the bug this hook caused in UAT: pulling the page down makes
  // iOS report a shifted visual viewport, the formula below read that as a
  // ~700px keyboard, and every fixed bottom sheet got lifted that far up —
  // sliding the *closed* Customize sheet into view on every scroll. A keyboard
  // is only possible when something focusable for text has focus.
  if (!keyboardCouldBeOpen()) return 0

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
    // Focus changes decide whether a keyboard is even possible, so recompute
    // on them too — otherwise the inset would stay stale after a field blurs.
    window.addEventListener('focusin', handleChange)
    window.addEventListener('focusout', handleChange)
    // Sync once on mount in case the keyboard is already open.
    handleChange()

    return () => {
      vv.removeEventListener('resize', handleChange)
      vv.removeEventListener('scroll', handleChange)
      window.removeEventListener('focusin', handleChange)
      window.removeEventListener('focusout', handleChange)
    }
  }, [])

  return { keyboardInset }
}
