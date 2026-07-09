/**
 * BenchmarkDrilldownSheet.tsx — Measured-vs-previous view for a benchmark
 * training log entry (D-10, D-12; 30-UI-SPEC § Training drill-down).
 *
 * Title "{date} — Benchmark: {facet}". Body: "Measured: {value}" /
 * "Previous: {previous_value}" — previous_value is supplied on the entry by
 * the /api/health/training payload (derived server-side from the prior
 * same-facet result); when it is null the sheet reads "Previous: —" rather
 * than fabricating a number. Uses DrilldownSheetShell (shared chrome),
 * default maxWidth 480 (no table here).
 */
import { DrilldownSheetShell } from './DrilldownSheetShell'
import { textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { BenchmarkLogEntry } from '../../../api/health'

interface BenchmarkDrilldownSheetProps {
  entry: BenchmarkLogEntry | null
  onClose: () => void
}

const rowLabelStyle: React.CSSProperties = {
  fontSize: typography.label.fontSize,
  color: textSecondary,
  fontFamily,
  marginBottom: '4px',
}

const rowValueStyle: React.CSSProperties = {
  fontSize: typography.body.fontSize,
  fontWeight: 600,
  color: textPrimary,
  fontFamily,
}

export function BenchmarkDrilldownSheet({ entry, onClose }: BenchmarkDrilldownSheetProps) {
  const measured = entry ? `${entry.value}${entry.unit ? ` ${entry.unit}` : ''}` : ''
  const previous =
    entry && entry.previous_value !== null
      ? `${entry.previous_value}${entry.unit ? ` ${entry.unit}` : ''}`
      : '—'

  return (
    <DrilldownSheetShell
      open={entry !== null}
      onClose={onClose}
      title={entry ? `${entry.date} — Benchmark: ${entry.facet}` : ''}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div>
          <div style={rowLabelStyle}>Measured</div>
          <div style={rowValueStyle}>{`Measured: ${measured}`}</div>
        </div>
        <div>
          <div style={rowLabelStyle}>Previous</div>
          <div style={rowValueStyle}>{`Previous: ${previous}`}</div>
        </div>
        {entry?.notes && (
          <div>
            <div style={rowLabelStyle}>Notes</div>
            <div style={{ fontSize: typography.body.fontSize, color: textPrimary, fontFamily }}>{entry.notes}</div>
          </div>
        )}
      </div>
    </DrilldownSheetShell>
  )
}
