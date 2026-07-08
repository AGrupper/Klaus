/**
 * SubTabs.tsx — Full-width 3-way segmented control (Training/Nutrition/Sleep).
 *
 * Adapts SortGroupControl's SegmentedGroup button-row visuals (accent active
 * bg, secondary inactive bg, 32px height, border separators, 44px min touch
 * width, aria-pressed) — see frontend/src/components/tasks/SortGroupControl.tsx.
 *
 * Persists the active tab in localStorage['health-tab'] on every change,
 * defaulting to 'training' when no key is present (D-01, D-02). The parent
 * HealthPage (Plan 30-08) is notified of the active tab via the `onChange`
 * callback (fired once on mount with the initial/restored value, and again
 * on every subsequent tab change) so it can render the matching sub-page.
 */

import { useEffect, useRef, useState } from 'react'
import { accent, border, secondary, textPrimary, textSecondary, typography, fontFamily } from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type HealthTab = 'training' | 'nutrition' | 'sleep'

const DEFAULT_HEALTH_TAB: HealthTab = 'training'

const TAB_ORDER: { value: HealthTab; label: string }[] = [
  { value: 'training', label: 'Training' },
  { value: 'nutrition', label: 'Nutrition' },
  { value: 'sleep', label: 'Sleep' },
]

interface SubTabsProps {
  /** Notified with the active tab on mount and on every subsequent change. */
  onChange?: (tab: HealthTab) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readInitialTab(): HealthTab {
  const stored = localStorage.getItem('health-tab')
  if (stored === 'training' || stored === 'nutrition' || stored === 'sleep') {
    return stored
  }
  return DEFAULT_HEALTH_TAB
}

// ---------------------------------------------------------------------------
// SubTabs
// ---------------------------------------------------------------------------

export function SubTabs({ onChange }: SubTabsProps) {
  const [tab, setTab] = useState<HealthTab>(readInitialTab)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  // Notify the parent of the initial/restored value on mount (component is
  // the source of truth for the persisted tab; the parent has no other way
  // to learn it before first paint).
  useEffect(() => {
    onChangeRef.current?.(tab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleSelect(next: HealthTab) {
    setTab(next)
    localStorage.setItem('health-tab', next)
    onChangeRef.current?.(next)
  }

  return (
    <div
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
      {TAB_ORDER.map(({ value, label }, i) => {
        const active = tab === value
        return (
          <button
            key={value}
            onClick={() => handleSelect(value)}
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
