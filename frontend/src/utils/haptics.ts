/**
 * haptics.ts — a real tap you can feel, on iPhone.
 *
 * iOS Safari has no `navigator.vibrate`, but since iOS 17.4 toggling a
 * `<input type="checkbox" switch>` plays the system's selection haptic. We
 * keep one hidden switch off-screen and click it whenever an action deserves
 * physical confirmation (checking off a habit, picking a colour).
 *
 * Everything degrades silently: Android uses `navigator.vibrate`, older iOS
 * and desktop simply feel nothing. Never call this on scroll or hover — only
 * on a deliberate, state-changing tap.
 */

let hapticSwitch: HTMLInputElement | null = null

function ensureSwitch(): HTMLInputElement | null {
  if (typeof document === 'undefined') return null
  if (hapticSwitch?.isConnected) return hapticSwitch

  const input = document.createElement('input')
  input.type = 'checkbox'
  // The `switch` attribute is what makes iOS play the haptic; it is inert
  // everywhere else, so this is safe to set unconditionally.
  input.setAttribute('switch', '')
  input.setAttribute('aria-hidden', 'true')
  input.tabIndex = -1
  input.style.cssText =
    'position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;left:-9999px;'
  document.body.appendChild(input)
  hapticSwitch = input
  return input
}

/** Light selection tick — check-offs, swatch picks, toggles. */
export function tapFeedback(): void {
  try {
    const input = ensureSwitch()
    if (input) input.click()
    navigator.vibrate?.(8)
  } catch {
    // Haptics are a nicety; never let them break an interaction.
  }
}

/** Heavier double tick — a routine's ring closing, a streak advancing. */
export function successFeedback(): void {
  try {
    tapFeedback()
    setTimeout(tapFeedback, 90)
    navigator.vibrate?.([10, 40, 18])
  } catch {
    // ignored
  }
}
