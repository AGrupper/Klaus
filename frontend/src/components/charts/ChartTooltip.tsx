/**
 * ChartTooltip.tsx — Shared tooltip bubble rendered internally by
 * LineChart/BarChart on hover (desktop) or tap (phone), per 30-UI-SPEC
 * Interaction Contracts § Chart tap/hover tooltip (D-04).
 *
 * Chrome values reused from TaskDetailSheet.tsx / 30-UI-SPEC Color § Chart
 * chrome: #1A1A1A background, 1px #2A2A2A border, 8px border radius.
 * Label (13px) date/name row + Body (16px/600) value row.
 *
 * When `value` is null (a missing-data gap, D-08) the tooltip still renders
 * — reading "No data" in textSecondary instead of a value line — so gaps
 * are discoverable rather than silently invisible.
 */
import {
  secondary,
  border,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

export interface ChartTooltipProps {
  /** x label (date/name) shown as the tooltip's top row. */
  label: string
  /** Exact value to display, or null for a gap (renders "No data"). */
  value: string | null
  /** Pixel position within the chart's positioning container. */
  left: number
  top: number
}

export function ChartTooltip({ label, value, left, top }: ChartTooltipProps) {
  return (
    <div
      role="tooltip"
      style={{
        position: 'absolute',
        left,
        top,
        transform: 'translate(-50%, calc(-100% - 10px))',
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: '8px',
        padding: '6px 10px',
        pointerEvents: 'none',
        whiteSpace: 'nowrap',
        zIndex: 10,
      }}
    >
      <div
        style={{
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
          fontFamily,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: typography.body.fontSize,
          fontWeight: 600,
          lineHeight: typography.body.lineHeight,
          color: value === null ? textSecondary : textPrimary,
          fontFamily,
        }}
      >
        {value === null ? 'No data' : value}
      </div>
    </div>
  )
}
