/**
 * HabitRow.tsx — Single habit/supplement row in the Habits tab list.
 *
 * Pattern basis: TaskRow.tsx (Phase 27). Simplifications:
 *   - No swipe-to-delete (toggle check-off instead; delete is via kebab only)
 *   - No row collapse after check-off (habit stays visible — unlike tasks)
 *   - Check button is a toggle (done_today ↔ pending):
 *       - Habit type: immediate toggle (useCheckOffHabit)
 *       - Supplement type: tap → opens DoseEditSheet (caller handles via onOpenDose)
 *   - Slot chip: #2A2A2A bg, Label 13px, 3px 8px padding, borderRadius 6px
 *   - Dose label (supplement only): Label 13px textSecondary below slot/streak
 *
 * Security note (T-28-xss): name, dose rendered as plain React text children —
 * never via dangerouslySetInnerHTML.
 */
import { useState, useRef } from 'react'
import { MoreHorizontal, Check } from 'lucide-react'
import { useCheckOffHabit } from '../../hooks/useHabits'
import { useUndoStore } from '../../store/undoStore'
import { hardDeleteHabit } from '../../api/habits'
import type { Habit, HabitSlot } from '../../api/habits'
import {
  accent,
  border,
  destructive,
  dominant,
  secondary,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HabitRowProps {
  habit: Habit
  /** Tap habit body → open detail view (wired in Task 3 / HabitsPage) */
  onOpenDetail: (habit: Habit) => void
  /** Kebab "Edit" → open create/edit sheet */
  onOpenEdit: (habit: Habit) => void
  /** Supplement tap → open dose edit sheet */
  onOpenDose: (habit: Habit) => void
  /** Kebab "Delete" → soft delete + undo */
  onDelete: (habit: Habit) => void
}

// ---------------------------------------------------------------------------
// Slot chip
// ---------------------------------------------------------------------------

function SlotChip({ slot }: { slot: HabitSlot }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 8px',
        borderRadius: '6px',
        backgroundColor: border,       // #2A2A2A
        color: textSecondary,
        fontSize: typography.label.fontSize,
        fontFamily,
        flexShrink: 0,
      }}
    >
      {slot}
    </div>
  )
}

// ---------------------------------------------------------------------------
// HabitRow
// ---------------------------------------------------------------------------

export function HabitRow({ habit, onOpenDetail, onOpenEdit, onOpenDose, onDelete }: HabitRowProps) {
  const checkOffMutation = useCheckOffHabit()
  const undoActiveItem = useUndoStore((s) => s.activeItem)

  // Kebab (⋯) menu state
  const [kebabOpen, setKebabOpen] = useState(false)
  const kebabRef = useRef<HTMLDivElement>(null)

  const isDone = habit.done_today ?? false
  const streak = habit.streak ?? 0

  // ---------------------------------------------------------------------------
  // Check-off handler (habit type only — supplement opens dose sheet)
  // ---------------------------------------------------------------------------

  function handleCheckOff() {
    if (habit.type === 'supplement') {
      onOpenDose(habit)
      return
    }

    // Get today's date in Asia/Jerusalem (D-11: must be today or yesterday)
    const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })

    // If there's an existing undo item (different habit), fire its hard-delete now
    if (undoActiveItem && undoActiveItem.id !== habit.id && undoActiveItem.resourceType === 'habit') {
      hardDeleteHabit(undoActiveItem.id).catch(() => {})
    }

    checkOffMutation.mutate({
      habitId: habit.id,
      date: today,
      done: !isDone,
    })
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const rowStyle: React.CSSProperties = {
    position: 'relative',
    zIndex: kebabOpen ? 30 : undefined,
    overflow: kebabOpen ? 'visible' : 'hidden',
    backgroundColor: dominant,
    borderBottom: `1px solid ${border}`,
  }

  const innerStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    minHeight: '52px',
    padding: '8px 0',
    backgroundColor: dominant,
  }

  return (
    <div style={rowStyle}>
      <div style={innerStyle}>
        {/* Check button — 44px tap target (iOS HIG) */}
        <button
          onClick={handleCheckOff}
          style={{
            width: '44px',
            height: '44px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            border: 'none',
            backgroundColor: 'transparent',
            cursor: 'pointer',
            padding: 0,
          }}
          aria-label={isDone ? `Uncheck ${habit.name}` : `Mark ${habit.name} as done`}
        >
          {/* Filled accent circle when done, open circle when pending */}
          <div
            style={{
              width: '22px',
              height: '22px',
              borderRadius: '50%',
              border: isDone ? 'none' : `1.5px solid ${textSecondary}`,
              backgroundColor: isDone ? accent : 'transparent',
              transition: 'background-color 0.15s ease-out, border-color 0.15s ease-out',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {isDone && (
              <Check
                size={13}
                color="#FFFFFF"
                strokeWidth={3}
                style={{ opacity: 1, transition: 'opacity 0.15s ease-out' }}
                aria-hidden="true"
              />
            )}
          </div>
        </button>

        {/* Habit body — tap to open detail view */}
        <button
          onClick={() => onOpenDetail(habit)}
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-start',
            gap: '3px',
            border: 'none',
            backgroundColor: 'transparent',
            cursor: 'pointer',
            padding: '0 8px 0 0',
            minWidth: 0,
          }}
          aria-label={`View ${habit.name} details`}
        >
          {/* Name — Body 16px textPrimary */}
          <span
            style={{
              fontSize: typography.body.fontSize,
              fontFamily,
              color: textPrimary,
              textAlign: 'left',
              width: '100%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {habit.name}
          </span>

          {/* Slot chip + streak inline */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              flexWrap: 'wrap',
            }}
          >
            <SlotChip slot={habit.slot} />
            {streak > 0 && (
              <span
                style={{
                  fontSize: typography.label.fontSize,
                  fontFamily,
                  color: textSecondary,
                }}
              >
                · {streak}-day streak
              </span>
            )}
          </div>

          {/* Dose label (supplement only) — Label 13px textSecondary */}
          {habit.type === 'supplement' && habit.dose && (
            <span
              style={{
                fontSize: typography.label.fontSize,
                fontFamily,
                color: textSecondary,
              }}
            >
              {habit.name} — {habit.dose}
            </span>
          )}
        </button>

        {/* Kebab (⋯) options menu — phone and desktop */}
        <div
          ref={kebabRef}
          style={{ position: 'relative', flexShrink: 0, marginRight: '8px' }}
        >
          <button
            onClick={() => setKebabOpen((p) => !p)}
            aria-label="Habit options"
            style={{
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              cursor: 'pointer',
              borderRadius: '6px',
              transition: 'color 0.15s',
            }}
          >
            <MoreHorizontal size={16} strokeWidth={2} aria-hidden="true" />
          </button>

          {/* Kebab dropdown */}
          {kebabOpen && (
            <>
              {/* Click-outside dismiss */}
              <div
                onClick={() => setKebabOpen(false)}
                style={{ position: 'fixed', inset: 0, zIndex: 49 }}
                aria-hidden="true"
              />
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '100%',
                  marginTop: '4px',
                  backgroundColor: secondary,
                  border: `1px solid ${border}`,
                  borderRadius: '8px',
                  overflow: 'hidden',
                  zIndex: 50,
                  minWidth: '120px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                }}
              >
                <button
                  onClick={() => { setKebabOpen(false); onOpenEdit(habit) }}
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '10px 14px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    color: textPrimary,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  Edit
                </button>
                <button
                  onClick={() => { setKebabOpen(false); onDelete(habit) }}
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '10px 14px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    color: destructive,       // #EF4444
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  Delete habit
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
