/**
 * StrengthDrilldownSheet.tsx — Per-exercise set/rep/weight table for a
 * strength training log entry (D-10; 30-UI-SPEC § Training drill-down).
 *
 * Title "{date} — Strength". Table columns "Exercise" / "Sets × Reps" /
 * "Weight", one row per exercise (StrengthExercise from api/health.ts):
 * "Sets × Reps" reads set_count × the top/working set's reps, "Weight"
 * reads the top/working set's weight_kg. Uses DrilldownSheetShell (shared
 * chrome: z:190/191, scroll-lock, close-trap), maxWidth 560 for the table.
 */
import { DrilldownSheetShell } from './DrilldownSheetShell'
import { border, textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { StrengthLogEntry } from '../../../api/health'

interface StrengthDrilldownSheetProps {
  entry: StrengthLogEntry | null
  onClose: () => void
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 10px',
  fontSize: typography.label.fontSize,
  fontWeight: 600,
  color: textSecondary,
  fontFamily,
  borderBottom: `1px solid ${border}`,
}

const tdStyle: React.CSSProperties = {
  padding: '8px 10px',
  fontSize: typography.body.fontSize,
  color: textPrimary,
  fontFamily,
  borderBottom: `1px solid ${border}`,
}

export function StrengthDrilldownSheet({ entry, onClose }: StrengthDrilldownSheetProps) {
  const exercises = entry?.exercises ?? []

  return (
    <DrilldownSheetShell
      open={entry !== null}
      onClose={onClose}
      title={entry ? `${entry.date} — Strength` : ''}
      maxWidth={560}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thStyle}>Exercise</th>
            <th style={thStyle}>Sets × Reps</th>
            <th style={thStyle}>Weight</th>
          </tr>
        </thead>
        <tbody>
          {exercises.length === 0 ? (
            <tr>
              <td style={tdStyle} colSpan={3}>
                No exercises recorded.
              </td>
            </tr>
          ) : (
            exercises.map((ex, i) => {
              const reps = ex.top_set?.reps ?? ex.sets[0]?.reps ?? null
              const weight = ex.top_set?.weight_kg ?? ex.sets[0]?.weight_kg ?? null
              return (
                <tr key={`${ex.name}-${i}`}>
                  <td style={tdStyle}>{ex.name}</td>
                  <td style={tdStyle}>{reps !== null ? `${ex.set_count} × ${reps}` : `${ex.set_count} sets`}</td>
                  <td style={tdStyle}>{weight !== null ? `${weight} kg` : '—'}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </DrilldownSheetShell>
  )
}
