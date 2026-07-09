/**
 * TrainingLogEntry.tsx — Single row in the mixed reverse-chronological
 * training log (D-09, D-12; 30-UI-SPEC Component Inventory § Training).
 *
 * minHeight: 64px (named exception vs. the 52px HabitRow/TaskRow height —
 * training rows carry more information). 4px modality-colored left-border
 * stripe (reuses the DueTasksBand/HabitsBand accent-stripe convention,
 * recolored per modality instead of accent): strength #FB923C, run #38BDF8,
 * benchmark #A78BFA. Benchmark rows additionally get an {benchmarkColor}14
 * (8% opacity) tinted row background (D-12 highlight).
 *
 * Tapping the row invokes onSelect(entry) — the matching drill-down sheet is
 * wired one level up, at TrainingHistoryPage (Task 3).
 */
import { ChevronRight } from 'lucide-react'
import { textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { TrainingLogEntryData } from '../../../api/health'

const STRENGTH_COLOR = '#FB923C'
const RUN_COLOR = '#38BDF8'
const BENCHMARK_COLOR = '#A78BFA'

interface ModalityMeta {
  color: string
  badge: string
  title: string
  summary: string
}

function formatPace(secPerKm: number | null | undefined): string {
  if (secPerKm === null || secPerKm === undefined) return 'No pace data'
  const min = Math.floor(secPerKm / 60)
  const sec = Math.round(secPerKm % 60)
  return `${min}:${String(sec).padStart(2, '0')}/km`
}

function getModalityMeta(entry: TrainingLogEntryData): ModalityMeta {
  switch (entry.modality) {
    case 'strength': {
      const exerciseCount = entry.exercises?.length ?? 0
      return {
        color: STRENGTH_COLOR,
        badge: 'Strength',
        title: entry.title || 'Strength Session',
        summary:
          `${exerciseCount} exercise${exerciseCount === 1 ? '' : 's'} · ` +
          `${Math.round(entry.total_volume_kg)} kg volume`,
      }
    }
    case 'run': {
      const km = entry.distance_m ? (entry.distance_m / 1000).toFixed(1) : null
      return {
        color: RUN_COLOR,
        badge: 'Run',
        title: entry.type || 'Run',
        summary: km
          ? `${km} km · ${formatPace(entry.avg_pace_sec_per_km)}`
          : formatPace(entry.avg_pace_sec_per_km),
      }
    }
    case 'benchmark': {
      return {
        color: BENCHMARK_COLOR,
        badge: 'Benchmark',
        title: entry.facet,
        summary: `Measured: ${entry.value}${entry.unit ? ` ${entry.unit}` : ''}`,
      }
    }
  }
}

interface TrainingLogEntryProps {
  entry: TrainingLogEntryData
  onSelect: (entry: TrainingLogEntryData) => void
}

export function TrainingLogEntry({ entry, onSelect }: TrainingLogEntryProps) {
  const meta = getModalityMeta(entry)
  const isBenchmark = entry.modality === 'benchmark'

  return (
    <button
      onClick={() => onSelect(entry)}
      data-modality={entry.modality}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        width: '100%',
        minHeight: '64px',
        padding: '10px 14px',
        border: 'none',
        borderLeft: `4px solid ${meta.color}`,
        backgroundColor: isBenchmark ? `${BENCHMARK_COLOR}14` : 'transparent',
        cursor: 'pointer',
        textAlign: 'left',
        fontFamily,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: typography.label.fontSize,
            fontWeight: 600,
            color: meta.color,
            fontFamily,
            marginBottom: '2px',
          }}
        >
          {meta.badge}
        </div>
        <div
          style={{
            fontSize: typography.body.fontSize,
            fontWeight: typography.body.fontWeight,
            lineHeight: typography.body.lineHeight,
            color: textPrimary,
            fontFamily,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {meta.title}
        </div>
        <div
          style={{
            fontSize: typography.label.fontSize,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {meta.summary}
        </div>
      </div>
      <ChevronRight size={18} color={textSecondary} aria-hidden="true" style={{ flexShrink: 0 }} />
    </button>
  )
}
