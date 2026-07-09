/**
 * SlotAdherenceGrid.tsx — Contribution-style fueling-slot adherence grid
 * (30-UI-SPEC Component Inventory § SlotAdherenceGrid, D-13).
 *
 * Adapted from ContributionGrid.tsx (Phase 28): pure CSS `display:grid`,
 * 12×12px cells, 2px gap (named spacing exception — do NOT round up to 4px,
 * it destroys the density aesthetic), gridAutoFlow: column, overflowX auto
 * with auto-scroll-to-newest on mount (scrollLeft = scrollWidth).
 *
 * Differences from ContributionGrid: rows = fueling-slot LABELS present in
 * the range (not weekdays — no mondayIndex/leadingPad logic), columns = days
 * in range, and a 2-state fill (hit #38BDF8 / miss #1F1F1F per 30-UI-SPEC
 * Color § slot grid) instead of 4-state.
 *
 * INVARIANT (CLAUDE.md §6, D-13/D-16, T-30-06-01): cells and labels key on
 * the fueling-slot LABEL only ("Post-lift"/"Evening"/…) — no clock time is
 * ever derived or rendered. The API already strips the canonical
 * 08:00/12:00/20:00 slot timestamps server-side; this component renders
 * `slot_label` strings verbatim.
 *
 * Accessibility: role="grid" on the container; each cell has role="gridcell"
 * and aria-label="{date}, {slot}: {logged|not logged}" — slot NAME, never a
 * time. aria-labels are plain text interpolated from typed API fields — no
 * innerHTML (same T-28-xss posture as ContributionGrid).
 *
 * Tapping a cell fires onDaySelect(date) — the page opens DayDrilldownSheet.
 */
import { useEffect, useRef } from 'react'
import type { SlotAdherenceGridData } from '../../../api/health'
import { skeleton, textSecondary, typography, fontFamily } from '../../../tokens'

/** Cell fill when a meal was logged in that slot on that day (sky-400). */
const HIT_COLOR = '#38BDF8'
/** Cell fill when no meal was logged — skeleton token (#1F1F1F), NOT a zero. */
const MISS_COLOR = skeleton

interface SlotAdherenceGridProps {
  data: SlotAdherenceGridData
  onDaySelect: (date: string) => void
}

export function SlotAdherenceGrid({ data, onDaySelect }: SlotAdherenceGridProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  const numSlots = data.grid.length
  const numDays = data.dates.length

  // Show the newest day by default: the right-most column is the most recent,
  // so scroll the container fully right on mount / when the data changes
  // (mirrors ContributionGrid's scrollLeft = scrollWidth behavior).
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [data])

  if (numSlots === 0 || numDays === 0) {
    return (
      <p
        style={{
          margin: 0,
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
          fontFamily,
          textAlign: 'center',
          padding: '24px 0',
        }}
      >
        No meals logged yet in this range.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
      {/* Row axis: fueling-slot LABELS (slot names only — never a time). */}
      <div
        style={{
          display: 'grid',
          gridTemplateRows: `repeat(${numSlots}, 12px)`,
          gap: '2px',
          flexShrink: 0,
        }}
        aria-hidden="true"
      >
        {data.grid.map((row) => (
          <span
            key={row.slot_label}
            style={{
              fontSize: '10px',
              lineHeight: '12px',
              color: textSecondary,
              fontFamily,
              whiteSpace: 'nowrap',
            }}
          >
            {row.slot_label}
          </span>
        ))}
      </div>

      {/* Scrollable day columns — auto-scrolled to the newest day on mount. */}
      <div
        ref={scrollRef}
        style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}
      >
        <div
          role="grid"
          aria-label="Fueling slot adherence grid"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${numDays}, 12px)`,
            gridTemplateRows: `repeat(${numSlots}, 12px)`,
            // column-fill order: one column per day, rows are slots.
            gridAutoFlow: 'column',
            // named exception: 2px not 4px (preserves grid density aesthetic)
            gap: '2px',
            width: 'max-content',
          }}
        >
          {data.dates.map((date, dayIdx) =>
            data.grid.map((row) => {
              const cell = row.cells[dayIdx]
              const hit = cell?.hit ?? false
              return (
                <div
                  key={`${date}-${row.slot_label}`}
                  role="gridcell"
                  aria-label={`${date}, ${row.slot_label}: ${hit ? 'logged' : 'not logged'}`}
                  onClick={() => onDaySelect(date)}
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 2,
                    backgroundColor: hit ? HIT_COLOR : MISS_COLOR,
                    flexShrink: 0,
                    cursor: 'pointer',
                  }}
                />
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
