/**
 * NowLine.tsx — Accent horizontal rule at the current time position (D-04).
 *
 * UI-SPEC constraints:
 *   - Color: accent #6366F1 (indigo-500) — reserved exclusively for the now-line (UI-SPEC § Color)
 *   - Auto-scroll on open: scrollIntoView({ behavior: 'smooth', block: 'center' }) on mount (D-04)
 *   - Shows current time as a Label string to the left of the line
 *
 * TimelineDay interleaves this component between past and upcoming timed events.
 * The NowLine does not need to know about the event list — it is always rendered
 * at the current moment in time.
 *
 * scrollIntoView is called in a useEffect with an empty dependency array (runs once
 * on initial mount). In jsdom tests, scrollIntoView is not implemented — test files
 * must mock it: `window.HTMLElement.prototype.scrollIntoView = vi.fn()`.
 */

import { useEffect, useRef } from 'react'
import {
  accent,
  typography,
  fontFamily,
} from '../../tokens'

/** Format a Date to "HH:MM" in locale format. */
function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-IL', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function NowLine() {
  const lineRef = useRef<HTMLDivElement>(null)
  const now = new Date()

  // D-04: auto-scroll to the now-line on initial mount
  useEffect(() => {
    if (lineRef.current) {
      lineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, []) // run once on mount

  return (
    <div
      ref={lineRef}
      role="separator"
      aria-label={`Current time: ${formatTime(now)}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        margin: '4px 0',
      }}
    >
      {/* Current time label */}
      <span
        style={{
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: accent,
          fontFamily,
          flexShrink: 0,
          minWidth: '44px',
          textAlign: 'right',
        }}
      >
        {formatTime(now)}
      </span>

      {/* The accent horizontal rule */}
      <div
        style={{
          flex: 1,
          height: '2px',
          backgroundColor: accent,
          borderRadius: '1px',
        }}
        aria-hidden="true"
      />

      {/* Small circle dot at the left edge of the rule */}
      <div
        style={{
          position: 'absolute',
          // Decorative marker only — screen readers skip this
        }}
        aria-hidden="true"
      />
    </div>
  )
}
