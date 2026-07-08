/**
 * RangeToggle.tsx — Controlled 4-way segmented control (7d/30d/90d/1y).
 *
 * Same SegmentedGroup visual pattern as SubTabs (accent active bg, secondary
 * inactive bg, 32px height, border separators, 44px min touch width,
 * aria-pressed) — see frontend/src/components/tasks/SortGroupControl.tsx.
 *
 * NOT persisted (D-06): this component holds no state of its own and does not
 * read or write browser storage. The owning sub-page (Training/Nutrition/Sleep)
 * owns the `useState<RangeKey>('30d')` and passes `value`/`onChange` — so the
 * range always resets to '30d' on every sub-page mount / navigation.
 */

import { accent, border, secondary, textPrimary, textSecondary, typography, fontFamily } from '../../tokens'
import type { RangeKey } from '../../api/health'

const RANGE_ORDER: { value: RangeKey; label: string }[] = [
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: '1y', label: '1y' },
]

interface RangeToggleProps {
  value: RangeKey
  onChange: (range: RangeKey) => void
}

export function RangeToggle({ value, onChange }: RangeToggleProps) {
  return (
    <div
      role="group"
      aria-label="Date range"
      style={{
        display: 'flex',
        width: '100%',
        borderRadius: '8px',
        border: `1px solid ${border}`,
        overflow: 'hidden',
        backgroundColor: secondary,
        color: textPrimary,
      }}
    >
      {RANGE_ORDER.map(({ value: rangeValue, label }, i) => {
        const active = value === rangeValue
        return (
          <button
            key={rangeValue}
            onClick={() => onChange(rangeValue)}
            aria-pressed={active}
            style={{
              flex: 1,
              height: '32px',
              minWidth: '44px', // touch target width
              padding: '0 10px',
              border: 'none',
              borderLeft: i > 0 ? `1px solid ${border}` : 'none',
              backgroundColor: active ? accent : secondary,
              color: active ? '#FFFFFF' : textSecondary,
              fontSize: typography.label.fontSize,
              fontWeight: active ? 600 : 400,
              fontFamily,
              cursor: 'pointer',
              transition: 'background-color 0.15s, color 0.15s',
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
