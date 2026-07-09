/**
 * TrainingHistoryPage.tsx — Root content for the Training sub-tab (HLTH-01).
 *
 * RangeToggle at top (owns useState<RangeKey>('30d') — NOT persisted, D-06),
 * then TrainingTrendCharts (Weekly Volume + Pace & Distance, D-11), then the
 * mixed reverse-chronological TrainingLog (D-09, D-12). Changing the range
 * triggers a new useTrainingHistory query key; Skeleton blocks replace the
 * charts + log rows during the initial fetch for a range.
 *
 * Entry taps route to the matching drill-down sheet (D-10) — one sheet-open
 * state at page level, narrowed by the entry's modality discriminant.
 *
 * Error state copy per 30-UI-SPEC Copywriting Contract:
 * "Couldn't load training history — pull to refresh."
 */
import { useState } from 'react'
import { useTrainingHistory } from '../../../hooks/useHealth'
import { RangeToggle } from '../RangeToggle'
import { TrainingTrendCharts } from './TrainingTrendCharts'
import { TrainingLog } from './TrainingLog'
import { StrengthDrilldownSheet } from './StrengthDrilldownSheet'
import { RunDrilldownSheet } from './RunDrilldownSheet'
import { BenchmarkDrilldownSheet } from './BenchmarkDrilldownSheet'
import { Skeleton } from '../../shared/Skeleton'
import { textSecondary, typography, fontFamily } from '../../../tokens'
import type { RangeKey, TrainingLogEntryData } from '../../../api/health'

function LoadingSkeletons() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Skeleton className="h-[200px] w-full" aria-label="Loading training history…" />
        <Skeleton className="h-[200px] w-full" aria-label="Loading training history…" />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <Skeleton className="h-16 w-full" aria-label="Loading training history…" />
        <Skeleton className="h-16 w-full" aria-label="Loading training history…" />
        <Skeleton className="h-16 w-full" aria-label="Loading training history…" />
      </div>
    </div>
  )
}

export function TrainingHistoryPage() {
  const [range, setRange] = useState<RangeKey>('30d')
  const [selectedEntry, setSelectedEntry] = useState<TrainingLogEntryData | null>(null)
  const { data, isLoading, isError } = useTrainingHistory(range)

  const closeSheet = () => setSelectedEntry(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <RangeToggle value={range} onChange={setRange} />

      {isError ? (
        <p
          style={{
            margin: 0,
            textAlign: 'center',
            padding: '24px 16px',
            fontSize: typography.label.fontSize,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          Couldn&apos;t load training history — pull to refresh.
        </p>
      ) : isLoading || !data ? (
        <LoadingSkeletons />
      ) : (
        <>
          <TrainingTrendCharts runMileage={data.run_mileage} runTrend={data.run_trend} />
          {/* 24px gap between the trend-chart row and the log list (lg token) */}
          <div style={{ marginTop: '8px' }}>
            <TrainingLog entries={data.entries} blocks={data.blocks} onSelect={setSelectedEntry} />
          </div>
        </>
      )}

      {/* Drill-down sheets — one open at a time, keyed off the selected entry's modality (D-10) */}
      <StrengthDrilldownSheet
        entry={selectedEntry?.modality === 'strength' ? selectedEntry : null}
        onClose={closeSheet}
      />
      <RunDrilldownSheet
        entry={selectedEntry?.modality === 'run' ? selectedEntry : null}
        onClose={closeSheet}
      />
      <BenchmarkDrilldownSheet
        entry={selectedEntry?.modality === 'benchmark' ? selectedEntry : null}
        onClose={closeSheet}
      />
    </div>
  )
}
