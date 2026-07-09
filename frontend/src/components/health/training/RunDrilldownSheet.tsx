/**
 * RunDrilldownSheet.tsx — Per-lap table for a run training log entry
 * (D-10; 30-UI-SPEC § Training drill-down).
 *
 * Title "{date} — Run". Table columns "Lap" / "Pace" / "HR", one row per
 * split (RunLap from api/health.ts — see mcp_tools/garmin_tool.py
 * ::_extract_splits for the canonical field set: index, pace_sec_per_km,
 * avg_hr). Uses DrilldownSheetShell (shared chrome), maxWidth 560 for the
 * table.
 */
import { DrilldownSheetShell } from './DrilldownSheetShell'
import { border, textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { RunLogEntry } from '../../../api/health'

interface RunDrilldownSheetProps {
  entry: RunLogEntry | null
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

function formatPace(secPerKm: unknown): string {
  if (typeof secPerKm !== 'number') return '—'
  // Round to whole seconds FIRST, then split — rounding the remainder
  // independently can yield an invalid "5:60/km" (WR-05).
  const total = Math.round(secPerKm)
  const min = Math.floor(total / 60)
  const sec = total % 60
  return `${min}:${String(sec).padStart(2, '0')}/km`
}

export function RunDrilldownSheet({ entry, onClose }: RunDrilldownSheetProps) {
  const splits = entry?.splits ?? []

  return (
    <DrilldownSheetShell
      open={entry !== null}
      onClose={onClose}
      title={entry ? `${entry.date} — Run` : ''}
      maxWidth={560}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thStyle}>Lap</th>
            <th style={thStyle}>Pace</th>
            <th style={thStyle}>HR</th>
          </tr>
        </thead>
        <tbody>
          {splits.length === 0 ? (
            <tr>
              <td style={tdStyle} colSpan={3}>
                No lap data recorded.
              </td>
            </tr>
          ) : (
            splits.map((lap, i) => {
              const index = typeof lap.index === 'number' ? lap.index : i + 1
              const avgHr = typeof lap.avg_hr === 'number' ? String(Math.round(lap.avg_hr)) : '—'
              return (
                <tr key={`lap-${index}`}>
                  <td style={tdStyle}>{index}</td>
                  <td style={tdStyle}>{formatPace(lap.pace_sec_per_km)}</td>
                  <td style={tdStyle}>{avgHr}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </DrilldownSheetShell>
  )
}
