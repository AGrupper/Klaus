/**
 * BlockDivider.tsx — Full-width row marking a training-block boundary inside
 * the mixed TrainingLog stream (D-09, D-12; 30-UI-SPEC Component Inventory).
 *
 * `#111118` background (reuses the existing band-background color from
 * DueTasksBand/HabitsBand), `10px 14px` padding, Label(13px) textSecondary
 * "Block {block_number} — {label}" — using only the two server-derived
 * fields on TrainingBlock (block_number, label) from the /api/health/training
 * payload. No other block-title field exists on the wire; do not invent one.
 */
import { textSecondary, typography, fontFamily } from '../../../tokens'
import type { TrainingBlock } from '../../../api/health'

interface BlockDividerProps {
  block: TrainingBlock
}

export function BlockDivider({ block }: BlockDividerProps) {
  return (
    <div
      style={{
        backgroundColor: '#111118',
        padding: '10px 14px',
      }}
    >
      <span
        style={{
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
          fontFamily,
        }}
      >
        {`Block ${block.block_number} — ${block.label}`}
      </span>
    </div>
  )
}
