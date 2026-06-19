/**
 * RecurrenceSelector.tsx — Inline recurrence cadence + anchor control.
 *
 * Renders:
 *   1. Cadence select: "Does not repeat" / "Daily" / "Weekdays" / "Weekly" /
 *      "Monthly" / "Every N days"
 *   2. Every-N input (only when cadence = "Every N days")
 *   3. Anchor toggle: "Stick to schedule" / "From completion"
 *      (hidden when cadence = "Does not repeat")
 *
 * Maps UI labels ↔ RecurrenceRule shape from TaskStore (27-01):
 *   - "Daily"         → cadence: 'daily'
 *   - "Weekdays"      → cadence: 'weekdays'
 *   - "Weekly"        → cadence: 'weekly'
 *   - "Monthly"       → cadence: 'monthly'
 *   - "Every N days"  → cadence: 'every_n_days', every_n: N
 *   - anchor: "Stick to schedule" → 'schedule'; "From completion" → 'completion'
 */

import { type RecurrenceRule } from '../../api/tasks'
import {
  border,
  dominant,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RecurrenceSelectorProps {
  /** Current recurrence rule, or null for "Does not repeat". */
  value: RecurrenceRule | null
  /** Called with the new rule (or null when cadence = "Does not repeat"). */
  onChange: (rule: RecurrenceRule | null) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type CadenceKey = 'none' | 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'every_n_days'

const CADENCE_OPTIONS: { value: CadenceKey; label: string }[] = [
  { value: 'none',         label: 'Does not repeat' },
  { value: 'daily',        label: 'Daily' },
  { value: 'weekdays',     label: 'Weekdays' },
  { value: 'weekly',       label: 'Weekly' },
  { value: 'monthly',      label: 'Monthly' },
  { value: 'every_n_days', label: 'Every N days' },
]

function ruleToKey(rule: RecurrenceRule | null): CadenceKey {
  if (!rule) return 'none'
  return rule.cadence === 'every_n_days' ? 'every_n_days' : rule.cadence
}

function selectStyle(overrides?: React.CSSProperties): React.CSSProperties {
  return {
    width: '100%',
    padding: '10px 12px',
    backgroundColor: dominant,
    border: `1px solid ${border}`,
    borderRadius: '8px',
    color: textPrimary,
    fontSize: typography.body.fontSize,
    fontFamily,
    cursor: 'pointer',
    outline: 'none',
    appearance: 'none' as const,
    ...overrides,
  }
}

function inputStyle(overrides?: React.CSSProperties): React.CSSProperties {
  return {
    padding: '10px 12px',
    backgroundColor: dominant,
    border: `1px solid ${border}`,
    borderRadius: '8px',
    color: textPrimary,
    fontSize: typography.body.fontSize,
    fontFamily,
    outline: 'none',
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// RecurrenceSelector
// ---------------------------------------------------------------------------

export function RecurrenceSelector({ value, onChange }: RecurrenceSelectorProps) {
  const cadenceKey = ruleToKey(value)

  function handleCadenceChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const key = e.target.value as CadenceKey
    if (key === 'none') {
      onChange(null)
      return
    }
    if (key === 'every_n_days') {
      onChange({
        cadence: 'every_n_days',
        every_n: value?.every_n ?? 7,
        anchor: value?.anchor ?? 'schedule',
      })
      return
    }
    onChange({
      cadence: key as RecurrenceRule['cadence'],
      anchor: value?.anchor ?? 'schedule',
    })
  }

  function handleNChange(e: React.ChangeEvent<HTMLInputElement>) {
    const n = parseInt(e.target.value, 10)
    if (!Number.isNaN(n) && n > 0) {
      onChange({
        cadence: 'every_n_days',
        every_n: n,
        anchor: value?.anchor ?? 'schedule',
      })
    }
  }

  function handleAnchorChange(e: React.ChangeEvent<HTMLSelectElement>) {
    if (!value) return
    onChange({
      ...value,
      anchor: e.target.value as 'schedule' | 'completion',
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* Cadence select */}
      <div style={{ position: 'relative' }}>
        <select
          value={cadenceKey}
          onChange={handleCadenceChange}
          style={selectStyle()}
          aria-label="Recurrence cadence"
        >
          {CADENCE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {/* Custom chevron */}
        <span
          style={{
            position: 'absolute',
            right: '12px',
            top: '50%',
            transform: 'translateY(-50%)',
            pointerEvents: 'none',
            color: textSecondary,
            fontSize: '12px',
          }}
        >
          ▾
        </span>
      </div>

      {/* Every-N input */}
      {cadenceKey === 'every_n_days' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: typography.label.fontSize, fontFamily, color: textSecondary, flexShrink: 0 }}>
            Every
          </span>
          <input
            type="number"
            min={1}
            max={365}
            value={value?.every_n ?? 7}
            onChange={handleNChange}
            style={inputStyle({ width: '70px' })}
            aria-label="Repeat every N days"
          />
          <span style={{ fontSize: typography.label.fontSize, fontFamily, color: textSecondary, flexShrink: 0 }}>
            days
          </span>
        </div>
      )}

      {/* Anchor toggle — only shown when recurrence is active */}
      {cadenceKey !== 'none' && (
        <div style={{ position: 'relative' }}>
          <select
            value={value?.anchor ?? 'schedule'}
            onChange={handleAnchorChange}
            style={selectStyle()}
            aria-label="Recurrence anchor"
          >
            <option value="schedule">Stick to schedule</option>
            <option value="completion">From completion</option>
          </select>
          <span
            style={{
              position: 'absolute',
              right: '12px',
              top: '50%',
              transform: 'translateY(-50%)',
              pointerEvents: 'none',
              color: textSecondary,
              fontSize: '12px',
            }}
          >
            ▾
          </span>
        </div>
      )}
    </div>
  )
}
