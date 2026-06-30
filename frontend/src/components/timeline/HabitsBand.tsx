/**
 * HabitsBand.tsx — Today timeline band for habits & supplements scheduled today.
 *
 * UI-SPEC (§ HabitsBand (Today timeline), TIME-06):
 *   - Rendered after DueTasksBand, before timed calendar events in TimelineDay.tsx
 *   - Renders nothing when no habit/supplement is scheduled today (guard: return null)
 *   - Section label "Habits" (13px textSecondary) with accent left-border stripe
 *     (4px × 32px, #6366F1) — mirrors DueTasksBand header exactly
 *   - Band-header padding: `10px 14px 6px` — named exception (UI-SPEC Spacing line 54)
 *   - Slot-group order: Morning → Noon → Evening → Bedtime → "any time"
 *   - Per row: CheckButton 44px + habit name (Body 16px) + dose pill (supplements) + slot chip
 *   - Tap habit → immediate useCheckOffHabit toggle (D-07)
 *   - Tap supplement → open DoseEditSheet (D-09)
 *
 * Divergences from DueTasksBand:
 *   - NO title-tap navigation — habit name is NOT a link; do not use useNavigate on title
 *   - Supplements show a dose pill ("5g") at Label 13px in border background beside the name
 *   - Supplement tap opens DoseEditSheet; habit tap toggles immediately
 *   - No row collapse after check-off (toggle, not one-shot completion)
 *
 * Security (T-28-xss): habit name and dose rendered as plain React text only —
 * no raw HTML injection.
 *
 * Display (T-28-display): responsive show/hide via Tailwind classes only —
 * no inline display overrides (band inherits TimelineDay layout).
 */

import { useState } from 'react'
import { Circle, CheckCircle2 } from 'lucide-react'
import { useHabits, useCheckOffHabit } from '../../hooks/useHabits'
import { DoseEditSheet } from '../habits/DoseEditSheet'
import type { Habit, HabitSlot } from '../../api/habits'
import {
  accent,
  border,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Slot ordering: Morning → Noon → Evening → Bedtime → "any time"
// ---------------------------------------------------------------------------

const SLOT_ORDER: HabitSlot[] = ['Morning', 'Noon', 'Evening', 'Bedtime']

function slotRank(slot: string | undefined): number {
  const idx = SLOT_ORDER.indexOf(slot as HabitSlot)
  return idx === -1 ? SLOT_ORDER.length : idx
}

// ---------------------------------------------------------------------------
// Today ISO date in Asia/Jerusalem (matches backend D-11 backfill gate)
// ---------------------------------------------------------------------------

function getTodayISO(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })
}

// ---------------------------------------------------------------------------
// SlotChip — slot label badge
// ---------------------------------------------------------------------------

function SlotChip({ slot }: { slot: HabitSlot }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 8px',
        borderRadius: '6px',
        backgroundColor: border,
        color: textSecondary,
        fontSize: typography.label.fontSize,
        fontFamily,
        flexShrink: 0,
        whiteSpace: 'nowrap',
      }}
    >
      {slot}
    </span>
  )
}

// ---------------------------------------------------------------------------
// DosePill — supplement dose badge (Label 13px, border background)
// ---------------------------------------------------------------------------

function DosePill({ dose }: { dose: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 8px',
        borderRadius: '6px',
        backgroundColor: border,
        color: textSecondary,
        fontSize: typography.label.fontSize,
        fontFamily,
        flexShrink: 0,
        whiteSpace: 'nowrap',
      }}
    >
      {dose}
    </span>
  )
}

// ---------------------------------------------------------------------------
// HabitsBandRow — single row inside the band
// ---------------------------------------------------------------------------

interface HabitsBandRowProps {
  habit: Habit
  onOpenDose: (habit: Habit) => void
}

function HabitsBandRow({ habit, onOpenDose }: HabitsBandRowProps) {
  const checkOffMutation = useCheckOffHabit()
  const [checking, setChecking] = useState(false)

  const isDone = !!habit.done_today

  function handleCheckButton(e: React.MouseEvent) {
    e.stopPropagation()

    if (habit.type === 'supplement') {
      // Supplements: open DoseEditSheet for dose confirmation (D-09)
      onOpenDose(habit)
      return
    }

    // Habits: immediate toggle (D-07 — tap again to uncheck)
    if (checking) return
    setChecking(true)
    const today = getTodayISO()
    checkOffMutation.mutate(
      { habitId: habit.id, date: today, done: !isDone },
      { onSettled: () => setChecking(false) },
    )
  }

  const ariaLabel = isDone
    ? `Uncheck ${habit.name}`
    : `Mark ${habit.name} as done`

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        minHeight: '44px',
        gap: '8px',
      }}
    >
      {/* CheckButton — 44px tap target (filled accent circle when done, open when pending) */}
      <button
        onClick={handleCheckButton}
        aria-label={ariaLabel}
        style={{
          width: '44px',
          height: '44px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: 'none',
          backgroundColor: 'transparent',
          cursor: 'pointer',
          flexShrink: 0,
          color: isDone ? accent : textSecondary,
          transition: 'color 0.15s ease-out',
        }}
      >
        {isDone ? (
          <CheckCircle2 size={20} strokeWidth={2} aria-hidden="true" />
        ) : (
          <Circle size={20} strokeWidth={1.5} aria-hidden="true" />
        )}
      </button>

      {/* Habit name — Body 16px, plain React text, NOT a link (divergence: no useNavigate) */}
      <span
        style={{
          flex: 1,
          color: textPrimary,
          fontSize: typography.body.fontSize,
          fontFamily,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {habit.name}
      </span>

      {/* Dose pill — supplements only, Label 13px in border background (T-28-xss: plain text) */}
      {habit.type === 'supplement' && habit.dose && (
        <DosePill dose={habit.dose} />
      )}

      {/* Slot chip */}
      <SlotChip slot={habit.slot} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// HabitsBand — main export
// ---------------------------------------------------------------------------

export function HabitsBand() {
  const { data: allHabits = [] } = useHabits()
  const [doseHabit, setDoseHabit] = useState<Habit | null>(null)
  const [doseOpen, setDoseOpen] = useState(false)

  // Filter to habits/supplements scheduled today (TIME-06 — flag set by GET /api/habits)
  // Sort by slot order: Morning → Noon → Evening → Bedtime → "any time"
  const scheduledToday = allHabits
    .filter((h) => h.scheduled_today === true)
    .slice()
    .sort((a, b) => slotRank(a.slot) - slotRank(b.slot))

  // Guard: render nothing when no items are scheduled today (no empty placeholder)
  if (scheduledToday.length === 0) return null

  function handleOpenDose(habit: Habit) {
    setDoseHabit(habit)
    setDoseOpen(true)
  }

  function handleCloseDose() {
    setDoseOpen(false)
    setDoseHabit(null)
  }

  return (
    <>
      <div
        style={{
          backgroundColor: '#111118',
          borderRadius: '10px',
          overflow: 'hidden',
        }}
      >
        {/* Section header: accent left-border stripe + "Habits" label */}
        {/* Padding: 10px 14px 6px — band-header named exception (UI-SPEC Spacing line 54) */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '10px 14px 6px',
          }}
        >
          {/* Accent stripe: 4px wide × 32px tall (mirrors DueTasksBand exactly) */}
          <div
            style={{
              width: '4px',
              height: '32px',
              borderRadius: '2px',
              backgroundColor: accent,
              flexShrink: 0,
            }}
            aria-hidden="true"
          />
          <span
            style={{
              fontSize: typography.label.fontSize,
              fontWeight: typography.label.fontWeight,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
              fontFamily,
            }}
          >
            Habits
          </span>
        </div>

        {/* Habit rows */}
        <div style={{ padding: '0 14px 10px' }}>
          {scheduledToday.map((habit) => (
            <HabitsBandRow
              key={habit.id}
              habit={habit}
              onOpenDose={handleOpenDose}
            />
          ))}
        </div>
      </div>

      {/* DoseEditSheet — mounted at band level, opened for supplement taps (D-09) */}
      <DoseEditSheet
        habit={doseHabit}
        open={doseOpen}
        onClose={handleCloseDose}
      />
    </>
  )
}
