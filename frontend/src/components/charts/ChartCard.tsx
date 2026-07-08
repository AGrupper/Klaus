/**
 * ChartCard.tsx — Card wrapper for chart primitives, matching the
 * GlanceRail/HabitRow card convention exactly (30-UI-SPEC Component
 * Inventory + Spacing § chart card padding).
 *
 * secondary bg, 1px border, 10px border radius, 16px padding. Optional
 * Body(16px/600) title slot above the chart content.
 */
import { secondary, border, textPrimary, typography, fontFamily } from '../../tokens'

interface ChartCardProps {
  /** Body(16px/600) heading rendered above the children, e.g. "Weekly Volume". */
  title?: string
  children: React.ReactNode
  className?: string
}

export function ChartCard({ title, children, className }: ChartCardProps) {
  return (
    <div
      className={className}
      style={{
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: 10,
        padding: 16,
      }}
    >
      {title && (
        <h3
          style={{
            margin: '0 0 12px 0',
            fontSize: typography.body.fontSize,
            fontWeight: 600,
            lineHeight: typography.body.lineHeight,
            color: textPrimary,
            fontFamily,
          }}
        >
          {title}
        </h3>
      )}
      {children}
    </div>
  )
}
