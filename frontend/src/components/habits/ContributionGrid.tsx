/**
 * ContributionGrid.tsx — GitHub-style 52×7 rolling year history grid.
 *
 * Pure CSS `display:grid` — no chart/heatmap library.
 *
 * Grid layout: 52 columns (weeks) × 7 rows (Mon–Sun from top).
 * Cells fill column-by-column via `grid-auto-flow: column` so each column is one
 * calendar week (Mon=row1 … Sun=row7) and the left-most column is the oldest week.
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
import type { GridCell, GridState } from '../../api/habits'
import { accent, border, skeleton } from '../../tokens'

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
   * Flat array of grid cells pre-sorted oldest-first.
   * The backend returns 364–365 cells spanning ~52 weeks. With grid-auto-flow:column,
   * the first 7 cells fill column 1 (Mon–Sun of the oldest week), the next 7 fill
   * column 2, and so on.
   */
  cells: GridCell[]
}

export function ContributionGrid({ cells }: ContributionGridProps) {
  return (
    <div
      role="grid"
      aria-label="Habit history grid"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(52, 12px)',
        gridTemplateRows: 'repeat(7, 12px)',
        // column-fill order: cell 1→7 = col 1 (Mon–Sun, oldest week),
        // cell 8→14 = col 2, …, cell 358→364 = col 52 (newest week)
        gridAutoFlow: 'column',
        // named exception: 2px not 4px (preserves GitHub-grid density aesthetic)
        gap: '2px',
        overflowX: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}
    >
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
  )
}
