/**
 * SortGroupControl.tsx — Sort + Group segmented controls for TaskListView.
 *
 * Renders two inline segmented button groups:
 *   Sort: "Due date" | "Priority"
 *   Group: "On" | "Off"
 *
 * D-18: day-scoped views (Today / Overdue) auto-sort by priority regardless
 * of the Sort selection — the caller passes `autoSort={true}` to suppress
 * the control UI in those contexts.
 *
 * State is local-only (no URL param). This component is purely presentational
 * — it calls back with the new value on change.
 */

import { accent, border, secondary, textPrimary, textSecondary, typography, fontFamily } from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SortMode = 'due_date' | 'priority'
export type GroupMode = 'on' | 'off'

export interface SortGroupState {
  sort: SortMode
  group: GroupMode
}

interface SortGroupControlProps {
  value: SortGroupState
  onChange: (next: SortGroupState) => void
  /** When true the Sort control is hidden and auto-sort by priority is implied (D-18). */
  autoSort?: boolean
}

// ---------------------------------------------------------------------------
// Segmented button helper
// ---------------------------------------------------------------------------

interface SegBtn {
  label: string
  value: string
  active: boolean
  onClick: () => void
}

function SegmentedGroup({
  label,
  buttons,
}: {
  label: string
  buttons: SegBtn[]
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span
        style={{
          ...typography.label,
          fontFamily,
          color: textSecondary,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <div
        style={{
          display: 'flex',
          borderRadius: '8px',
          border: `1px solid ${border}`,
          overflow: 'hidden',
        }}
      >
        {buttons.map((btn, i) => (
          <button
            key={btn.value}
            onClick={btn.onClick}
            style={{
              height: '32px',
              padding: '0 10px',
              border: 'none',
              borderLeft: i > 0 ? `1px solid ${border}` : 'none',
              backgroundColor: btn.active ? accent : secondary,
              color: btn.active ? '#FFFFFF' : textSecondary,
              fontSize: typography.label.fontSize,
              fontWeight: btn.active ? 600 : 400,
              fontFamily,
              cursor: 'pointer',
              transition: 'background-color 0.15s, color 0.15s',
              whiteSpace: 'nowrap',
              minWidth: '44px', // touch target width
            }}
            aria-pressed={btn.active}
          >
            {btn.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SortGroupControl
// ---------------------------------------------------------------------------

export function SortGroupControl({ value, onChange, autoSort = false }: SortGroupControlProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '8px 16px',
        borderBottom: `1px solid ${border}`,
        backgroundColor: secondary,
        flexWrap: 'wrap',
        minHeight: '44px', // touch target
        color: textPrimary,
      }}
    >
      {/* Sort group — hidden when auto-sort is active (D-18) */}
      {!autoSort && (
        <SegmentedGroup
          label="Sort"
          buttons={[
            {
              label: 'Due date',
              value: 'due_date',
              active: value.sort === 'due_date',
              onClick: () => onChange({ ...value, sort: 'due_date' }),
            },
            {
              label: 'Priority',
              value: 'priority',
              active: value.sort === 'priority',
              onClick: () => onChange({ ...value, sort: 'priority' }),
            },
          ]}
        />
      )}

      <SegmentedGroup
        label="Group"
        buttons={[
          {
            label: 'On',
            value: 'on',
            active: value.group === 'on',
            onClick: () => onChange({ ...value, group: 'on' }),
          },
          {
            label: 'Off',
            value: 'off',
            active: value.group === 'off',
            onClick: () => onChange({ ...value, group: 'off' }),
          },
        ]}
      />
    </div>
  )
}
