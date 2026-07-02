/**
 * ContributionGrid.tsx — GitHub-style rolling-year history grid.
 *
 * Pure CSS `display:grid` — no chart/heatmap library.
 *
 * Grid layout: N columns (weeks) × 7 rows (Mon=row1 … Sun=row7 from top).
 * Cells fill column-by-column via `grid-auto-flow: column` so each column is one
 * calendar week and the left-most column is the oldest week. To keep every cell
 * on its true weekday row, the first real cell is preceded by `leadingPad` empty
 * placeholder cells equal to the oldest date's Monday-index. The column count is
 * derived from `pad + cells` (≈53 for a full year) so the newest cell (today)
 * always has a real slot — a fixed 52-column grid drops the 365th cell into an
 * invisible implicit column (WR-03).
 *
 * The grid can exceed the viewport width on phones; the scroll container is
 * auto-scrolled to the right end on mount so today (the most recent, and for a
 * new habit the only coloured cell) is visible without manual scrolling.
 *
 * Each cell: 12×12px, borderRadius 2px, gap 2px between cells.
 * Gap is a named spacing exception (2px, not 4px) per the Phase 28 spacing scale —
 * rounding up to 4px destroys the GitHub-grid density aesthetic.
 *
 * Four-state cell colors:
 *   done           → accent   (#6366F1) from tokens.ts
 *   missed         → #3A1A1A  (only hardcoded hex allowed in the habits folder —
 *                              muted destructive tint, documented new value in 28-UI-SPEC)
 *   not-scheduled  → skeleton (#1F1F1F) from tokens.ts
 *   pending        → border   (#2A2A2A) from tokens.ts
 *
 * Accessibility: role="grid" on the container; each cell has role="gridcell"
 * and aria-label="{YYYY-MM-DD}: {state}".
 *
 * Security (T-28-xss): aria-label values are plain text interpolated from typed
 * API fields — no innerHTML or dangerouslySetInnerHTML.
 *
 * Display rule (T-28-display): no responsive wrapper — this component is always
 * visible when rendered. Responsive layout is handled by the parent (HabitDetailView).
 */
import { useEffect, useRef } from 'react'
import type { GridCell, GridState } from '../../api/habits'
import { accent, border, skeleton } from '../../tokens'

/**
 * Monday-based weekday index (0=Mon … 6=Sun) for a "YYYY-MM-DD" string.
 * Parsed as a local date-only value so no timezone shift moves the weekday.
 */
function mondayIndex(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  const jsDay = new Date(y, (m ?? 1) - 1, d ?? 1).getDay() // 0=Sun … 6=Sat
  return (jsDay + 6) % 7
}

// ---------------------------------------------------------------------------
// Cell color map (four-state)
// ---------------------------------------------------------------------------

/**
 * Contribution grid fill colors, keyed by GridState.
 *
 * Token sources (from frontend/src/tokens.ts):
 *   done           → accent   = '#6366F1'
 *   not-scheduled  → skeleton = '#1F1F1F'
 *   pending        → border   = '#2A2A2A'
 *
 * Exception (28-UI-SPEC Color § New additions):
 *   missed         → '#3A1A1A'  ← the ONLY hardcoded hex allowed in the habits folder.
 *
 * This object is exported so HabitDetailView can share the same fills for the legend.
 */
export const CELL_COLORS: Record<GridState, string> = {
  done: accent,
  missed: '#3A1A1A',
  'not-scheduled': skeleton,
  pending: border,
}

// ---------------------------------------------------------------------------
// ContributionGrid
// ---------------------------------------------------------------------------

interface ContributionGridProps {
  /**
   * Flat array of grid cells pre-sorted oldest-first (≈365 cells spanning ~53
   * weeks). With grid-auto-flow:column and a leading weekday pad, each column is
   * one calendar week (Mon=row1 … Sun=row7) and the last cell is today.
   */
  cells: GridCell[]
}

export function ContributionGrid({ cells }: ContributionGridProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Leading empty cells so the oldest date lands on its true weekday row.
  const leadingPad = cells.length > 0 ? mondayIndex(cells[0].date) : 0
  // Enough columns for the pad + every cell (≈53 for a full year) so today is
  // never pushed into an undefined implicit column and dropped off-screen.
  const numCols = Math.max(1, Math.ceil((leadingPad + cells.length) / 7))

  // Show today by default: today is the newest (right-most) cell, so scroll the
  // container fully right on mount / when the data changes.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [cells])

  return (
    <div
      ref={scrollRef}
      style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}
    >
      <div
        role="grid"
        aria-label="Habit history grid"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${numCols}, 12px)`,
          gridTemplateRows: 'repeat(7, 12px)',
          // column-fill order: pad + cell 1→7 = col 1 (Mon–Sun, oldest week), …
          gridAutoFlow: 'column',
          // named exception: 2px not 4px (preserves GitHub-grid density aesthetic)
          gap: '2px',
          width: 'max-content',
        }}
      >
        {/* Leading weekday alignment pad (transparent, non-interactive) */}
        {Array.from({ length: leadingPad }).map((_, i) => (
          <div key={`pad-${i}`} aria-hidden style={{ width: 12, height: 12 }} />
        ))}
        {cells.map((cell) => (
          <div
            key={cell.date}
            role="gridcell"
            aria-label={`${cell.date}: ${cell.state}`}
            style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              backgroundColor: CELL_COLORS[cell.state],
              flexShrink: 0,
            }}
          />
        ))}
      </div>
    </div>
  )
}
