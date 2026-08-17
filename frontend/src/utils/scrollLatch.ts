/**
 * scrollLatch — "did the page just move?", asked globally.
 *
 * Three attempts at stopping a pull-down from opening the Customize sheet all
 * failed because they reasoned from the *button's* events: which pointer
 * moves it saw, whether its touch was cancelled. If the browser routes the
 * gesture somewhere else and then emits a stray click, none of that helps.
 *
 * This asks a different question that doesn't depend on the target at all:
 * has anything scrolled in the last fraction of a second? Scroll and
 * touchmove are observed in the capture phase at the window, so every
 * scroller in the app — page, main column, sheet body — feeds the same latch,
 * and any activation arriving in that window is treated as gesture spill-over
 * rather than intent.
 */

/** Activations within this long after movement are treated as spill-over. */
const QUIET_PERIOD_MS = 450

let lastMovementAt = 0

function mark(): void {
  lastMovementAt = Date.now()
}

if (typeof window !== 'undefined') {
  const options = { capture: true, passive: true } as const
  window.addEventListener('scroll', mark, options)
  window.addEventListener('touchmove', mark, options)
  window.addEventListener('wheel', mark, options)
}

/** True when the page moved recently enough that a tap is probably spill-over. */
export function recentlyScrolled(withinMs: number = QUIET_PERIOD_MS): boolean {
  return Date.now() - lastMovementAt < withinMs
}

/** Test-only: pretend movement just happened / clear the latch. */
export function __setLastMovementForTests(at: number): void {
  lastMovementAt = at
}
