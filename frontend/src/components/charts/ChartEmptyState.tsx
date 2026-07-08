/**
 * ChartEmptyState.tsx — Centered empty-state message rendered in place of a
 * chart when its series has zero points (30-UI-SPEC: "no empty axes").
 *
 * Renders inside a ChartCard (caller wraps this in `<ChartCard>...`) — this
 * component only owns the centered Label(13px textSecondary) message, e.g.
 * "No data for this range." / "No nutrition data logged in this range."
 */
import { textSecondary, typography, fontFamily } from '../../tokens'

interface ChartEmptyStateProps {
  /** The exact copy string from the UI-SPEC Copywriting Contract. */
  text: string
  /** Matches the chart height it replaces so the card doesn't jump. */
  height?: number
}

export function ChartEmptyState({ text, height = 160 }: ChartEmptyStateProps) {
  return (
    <div
      style={{
        height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
      }}
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
