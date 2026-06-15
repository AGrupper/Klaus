/**
 * PlaceholderCard.tsx — D-06 "not yet available" placeholder.
 *
 * UI-SPEC distinction (important):
 *   - PlaceholderCard (this file): stable text for known-absent data.
 *     coach_note before morning briefing → "Coach note coming after your morning briefing."
 *     garmin before sync → "Sleep stats syncing…"
 *     NO shimmer / NO animate-pulse class.
 *
 *   - Skeleton (26-09, not yet shipped): animated shimmer (#1F1F1F) for in-flight
 *     API fetches. Skeleton is used when the query is loading; PlaceholderCard is
 *     used when the query succeeded but the field is null (D-06).
 *
 * Copywriting Contract strings must be passed in via the `text` prop — this
 * component is content-agnostic so it can be used for any D-06 placeholder.
 *
 * Usage:
 *   <PlaceholderCard text="Sleep stats syncing…" />
 *   <PlaceholderCard text="Coach note coming after your morning briefing." />
 *   <PlaceholderCard text="No meals logged yet today." />
 *   <PlaceholderCard text="No training scheduled today." />
 *   <PlaceholderCard text="Nothing on the calendar today." />
 */

import {
  secondary,
  border,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

interface PlaceholderCardProps {
  /** The exact copy string from the UI-SPEC Copywriting Contract. */
  text: string
  /** Optional additional styles on the wrapper card. */
  className?: string
}

export function PlaceholderCard({ text, className }: PlaceholderCardProps) {
  return (
    <div
      className={className}
      style={{
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: '10px',
        padding: '12px 16px',
        // NO animate-pulse / shimmer — this is a D-06 stable placeholder, NOT a skeleton
      }}
      aria-label={text}
    >
      <p
        style={{
          margin: 0,
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
          fontFamily,
        }}
      >
        {text}
      </p>
    </div>
  )
}
