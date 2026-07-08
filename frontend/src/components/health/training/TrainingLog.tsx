/**
 * TrainingLog.tsx — Reverse-chronological list mixing strength/run/benchmark
 * entries + BlockDivider rows, interleaved by date (D-09, D-12;
 * 30-UI-SPEC Component Inventory § Training).
 *
 * The backend already returns `entries` newest-first (health.ts JSDoc), but
 * this component re-sorts defensively by date descending so the interleave
 * contract holds regardless of the caller's array order.
 *
 * Block boundaries are resolved by date overlap against `blocks` (each block
 * carries only two server-derived title fields — `block_number` + `label`,
 * see TrainingBlock in api/health.ts). Walking newest→oldest, a BlockDivider
 * is inserted every time the resolved block changes.
 */
import { ChartEmptyState } from '../../charts/ChartEmptyState'
import { BlockDivider } from './BlockDivider'
import { TrainingLogEntry } from './TrainingLogEntry'
import type { TrainingLogEntryData, TrainingBlock } from '../../../api/health'

interface TrainingLogProps {
  entries: TrainingLogEntryData[]
  blocks: TrainingBlock[]
  onSelect: (entry: TrainingLogEntryData) => void
}

/** Resolve the block (if any) whose [start_date, end_date] contains `date`. */
function resolveBlock(date: string, blocks: TrainingBlock[]): TrainingBlock | null {
  return blocks.find((b) => date >= b.start_date && date <= b.end_date) ?? null
}

/** Stable per-entry React key across the discriminated modality union. */
function entryKey(entry: TrainingLogEntryData, index: number): string {
  switch (entry.modality) {
    case 'strength':
      return `strength-${entry.workout_id}`
    case 'run':
      return `run-${entry.activity_id}`
    case 'benchmark':
      return `benchmark-${entry.facet}-${entry.date}-${index}`
  }
}

export function TrainingLog({ entries, blocks, onSelect }: TrainingLogProps) {
  if (entries.length === 0) {
    return <ChartEmptyState text="No training logged in this range." />
  }

  const sorted = [...entries].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))

  let lastBlockNumber: number | null = null
  let sawFirstBlock = false
  const rows: React.ReactNode[] = []

  sorted.forEach((entry, i) => {
    const block = resolveBlock(entry.date, blocks)
    const blockNumber = block?.block_number ?? null
    if (!sawFirstBlock || blockNumber !== lastBlockNumber) {
      sawFirstBlock = true
      lastBlockNumber = blockNumber
      if (block) {
        rows.push(
          <BlockDivider key={`divider-${block.block_id ?? block.block_number}-${entry.date}`} block={block} />,
        )
      }
    }
    rows.push(<TrainingLogEntry key={entryKey(entry, i)} entry={entry} onSelect={onSelect} />)
  })

  return <div>{rows}</div>
}
