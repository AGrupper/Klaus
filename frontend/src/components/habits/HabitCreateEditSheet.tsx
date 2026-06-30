/**
 * HabitCreateEditSheet.tsx — Bottom sheet (phone) / centered modal (desktop) for
 * creating and editing habits and supplements.
 *
 * iOS safety (Phase 26/27 lessons — MANDATORY):
 *   - Scrim z:190 / sheet z:191 (beats BottomTabs z:100)
 *   - useVisualViewport keyboardInset to anchor sheet above iOS soft keyboard
 *   - scroll-lock: document.body.style.overflow = 'hidden' while open
 *   - NO autoFocus on phone (iOS layout-pan trap)
 *   - onMouseDown={e => e.preventDefault()} on dismiss/cancel buttons
 *
 * Display rule (T-28-display, Pitfall 2): FAB wrapper and phone/desktop
 * conditional rendering MUST use Tailwind classes — no inline style={{ display }}.
 *
 * Security (T-28-xss): name/dose rendered as input values — never via
 * dangerouslySetInnerHTML.
 *
 * Scheduled days S M T W T F S map to backend weekday ints (Mon=0, Sun=6):
 *   S=Sun(6), M=Mon(0), T=Tue(1), W=Wed(2), T=Thu(3), F=Fri(4), S=Sat(5)
 */
import { useState, useEffect } from 'react'
import { GripHorizontal } from 'lucide-react'
import { useCreateHabit, useEditHabit } from '../../hooks/useHabits'
import { useVisualViewport } from '../../hooks/useVisualViewport'
import type { Habit, HabitType, HabitSlot } from '../../api/habits'
import {
  accent,
  border,
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

interface HabitCreateEditSheetProps {
  /** null → create mode; Habit → edit mode */
  habit: Habit | null
  open: boolean
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Day chip data (S M T W T F S → backend ints Mon=0, Sun=6)
// ---------------------------------------------------------------------------

const DAY_CHIPS = [
  { label: 'S', day: 6 },  // Sunday
  { label: 'M', day: 0 },  // Monday
  { label: 'T', day: 1 },  // Tuesday
  { label: 'W', day: 2 },  // Wednesday
  { label: 'T', day: 3 },  // Thursday
  { label: 'F', day: 4 },  // Friday
  { label: 'S', day: 5 },  // Saturday
] as const

const SLOTS: HabitSlot[] = ['Morning', 'Noon', 'Evening', 'Bedtime']
const TYPES: HabitType[] = ['habit', 'supplement']
const TYPE_LABELS: Record<HabitType, string> = { habit: 'Habit', supplement: 'Supplement' }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label
      style={{
        display: 'block',
        fontSize: typography.label.fontSize,
        fontWeight: 600,
        fontFamily,
        color: textSecondary,
        marginBottom: '4px',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </label>
  )
}

const inputCss: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  backgroundColor: dominant,
  border: `1px solid ${border}`,
  borderRadius: '8px',
  color: textPrimary,
  fontSize: typography.body.fontSize,
  fontFamily,
  outline: 'none',
  boxSizing: 'border-box',
}

// ---------------------------------------------------------------------------
// HabitCreateEditSheet
// ---------------------------------------------------------------------------

export function HabitCreateEditSheet({ habit, open, onClose }: HabitCreateEditSheetProps) {
  const isCreate = habit === null

  const createHabit = useCreateHabit()
  const editHabit = useEditHabit(habit?.id ?? '')

  // Form state
  const [name, setName] = useState('')
  const [type, setType] = useState<HabitType>('habit')
  const [dose, setDose] = useState('')
  const [selectedDays, setSelectedDays] = useState<Set<number>>(
    new Set([0, 1, 2, 3, 4, 5, 6])  // all days selected by default (= "daily")
  )
  const [slot, setSlot] = useState<HabitSlot>('Morning')
  const [errorMsg, setErrorMsg] = useState('')

  // iOS keyboard inset
  const { keyboardInset } = useVisualViewport()

  // Slide-in animation
  const [slideIn, setSlideIn] = useState(false)

  // Populate form when habit changes
  useEffect(() => {
    if (habit) {
      setName(habit.name)
      setType(habit.type)
      setDose(habit.dose ?? '')
      setSlot(habit.slot)
      // Get the most recent schedule revision
      const lastRevision = habit.schedule_history?.[habit.schedule_history.length - 1]
      if (lastRevision) {
        if (lastRevision.days === 'daily') {
          setSelectedDays(new Set([0, 1, 2, 3, 4, 5, 6]))
        } else {
          setSelectedDays(new Set(lastRevision.days as number[]))
        }
      } else {
        setSelectedDays(new Set([0, 1, 2, 3, 4, 5, 6]))
      }
    } else {
      setName('')
      setType('habit')
      setDose('')
      setSelectedDays(new Set([0, 1, 2, 3, 4, 5, 6]))
      setSlot('Morning')
    }
    setErrorMsg('')
  }, [habit, open])

  // Slide-in animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  // Scroll lock while open (prevents iOS layout pan)
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open) return null

  // ---------------------------------------------------------------------------
  // Save handler
  // ---------------------------------------------------------------------------

  function handleSave() {
    setErrorMsg('')
    if (!name.trim()) {
      setErrorMsg("Name can't be empty.")
      return
    }
    if (selectedDays.size === 0) {
      setErrorMsg('At least one scheduled day is required.')
      return
    }

    // Compute days value: 'daily' if all 7 selected, else sorted array of ints
    const allDayInts = [0, 1, 2, 3, 4, 5, 6]
    const daysValue: 'daily' | number[] =
      allDayInts.every((d) => selectedDays.has(d))
        ? 'daily'
        : allDayInts.filter((d) => selectedDays.has(d))

    if (isCreate) {
      createHabit.mutate(
        {
          name: name.trim(),
          type,
          dose: type === 'supplement' && dose.trim() ? dose.trim() : null,
          slot,
          days: daysValue,
        },
        {
          onSuccess: () => { onClose() },
          onError: () => { setErrorMsg("Couldn't save — try again.") },
        },
      )
    } else if (habit) {
      editHabit.mutate(
        {
          name: name.trim(),
          type,
          dose: type === 'supplement' && dose.trim() ? dose.trim() : null,
          slot,
          days: daysValue,
        },
        {
          onSuccess: () => { onClose() },
          onError: () => { setErrorMsg("Couldn't update — try again.") },
        },
      )
    }
  }

  function toggleDay(day: number) {
    setSelectedDays((prev) => {
      const next = new Set(prev)
      if (next.has(day)) {
        if (next.size > 1) next.delete(day)  // ≥1 required
      } else {
        next.add(day)
      }
      return next
    })
  }

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768
  const ctaLabel = isCreate ? 'Add habit' : 'Save changes'

  return (
    <>
      {/* Scrim — z:190 beats BottomTabs (z:100) */}
      <div
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(10,10,10,0.7)',
          zIndex: 190,
        }}
        aria-hidden="true"
      />

      {/* Sheet / Modal — z:191 */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isCreate ? 'Add habit' : 'Edit habit'}
        style={{
          position: 'fixed',
          zIndex: 191,
          ...(isPhone
            ? {
                left: 0,
                right: 0,
                bottom: keyboardInset,
                maxHeight: `calc(100dvh - ${keyboardInset}px - 24px)`,
                borderRadius: '16px 16px 0 0',
                transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
                transition: 'transform 0.25s ease-out',
              }
            : {
                left: '50%',
                top: '50%',
                transform: slideIn
                  ? 'translate(-50%, -50%)'
                  : 'translate(-50%, calc(-50% + 20px))',
                transition: 'transform 0.25s ease-out, opacity 0.25s ease-out',
                maxWidth: '480px',
                width: '100%',
                maxHeight: '90dvh',
                borderRadius: '16px',
              }),
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Drag handle (phone only — class-driven, NOT inline display) */}
        <div
          className="md:hidden"
          style={{ display: 'flex', justifyContent: 'center', padding: '10px 0 4px' }}
          aria-hidden="true"
        >
          <GripHorizontal size={20} color={textSecondary} strokeWidth={2} />
        </div>

        {/* Form body — scrollable */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            minHeight: 0,
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {/* Error message */}
          {errorMsg && (
            <div
              role="alert"
              style={{
                padding: '10px 14px',
                backgroundColor: `rgba(239,68,68,0.13)`,
                border: `1px solid rgba(239,68,68,0.6)`,
                borderRadius: '8px',
                color: '#EF4444',
                fontSize: typography.label.fontSize,
                fontFamily,
              }}
            >
              {errorMsg}
            </div>
          )}

          {/* NAME */}
          <div>
            <FieldLabel>Name</FieldLabel>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Morning run"
              style={inputCss}
              // No autoFocus on phone (iOS layout-pan trap)
              autoFocus={!isPhone}
              maxLength={500}
            />
          </div>

          {/* TYPE segmented: Habit | Supplement */}
          <div>
            <FieldLabel>Type</FieldLabel>
            <div style={{ display: 'flex', gap: '8px' }}>
              {TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  style={{
                    flex: 1,
                    minHeight: '36px',
                    border: `1px solid ${border}`,
                    borderRadius: '8px',
                    backgroundColor: type === t ? accent : secondary,
                    color: type === t ? '#FFFFFF' : textSecondary,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    fontWeight: type === t ? 600 : 400,
                    transition: 'background-color 0.15s, color 0.15s',
                  }}
                >
                  {TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          </div>

          {/* DOSE (supplement only) */}
          {type === 'supplement' && (
            <div>
              <FieldLabel>Dose</FieldLabel>
              <input
                type="text"
                value={dose}
                onChange={(e) => setDose(e.target.value)}
                placeholder="e.g. 5g"
                style={inputCss}
                maxLength={200}
              />
            </div>
          )}

          {/* SCHEDULE — 7 day chips S M T W T F S */}
          <div>
            <FieldLabel>Schedule</FieldLabel>
            <div style={{ display: 'flex', gap: '6px' }}>
              {DAY_CHIPS.map(({ label, day }, idx) => {
                const isSelected = selectedDays.has(day)
                return (
                  <button
                    key={`${label}-${idx}`}
                    onClick={() => toggleDay(day)}
                    style={{
                      flex: 1,
                      minHeight: '36px',
                      border: `1px solid ${isSelected ? accent : border}`,
                      borderRadius: '6px',
                      backgroundColor: isSelected ? `${accent}22` : secondary,
                      color: isSelected ? accent : textSecondary,
                      fontSize: typography.label.fontSize,
                      fontFamily,
                      cursor: 'pointer',
                      fontWeight: isSelected ? 600 : 400,
                      padding: '0',
                      transition: 'background-color 0.15s, border-color 0.15s, color 0.15s',
                    }}
                    aria-pressed={isSelected}
                    aria-label={`${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][day]}`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* SLOT segmented: Morning | Noon | Evening | Bedtime */}
          <div>
            <FieldLabel>Slot</FieldLabel>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {SLOTS.map((s) => (
                <button
                  key={s}
                  onClick={() => setSlot(s)}
                  style={{
                    flex: '1 1 calc(50% - 3px)',
                    minHeight: '36px',
                    border: `1px solid ${border}`,
                    borderRadius: '8px',
                    backgroundColor: slot === s ? accent : secondary,
                    color: slot === s ? '#FFFFFF' : textSecondary,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    fontWeight: slot === s ? 600 : 400,
                    transition: 'background-color 0.15s, color 0.15s',
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Footer — CTA */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: `1px solid ${border}`,
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            paddingBottom: isPhone ? 'calc(env(safe-area-inset-bottom, 0px) + 12px)' : '12px',
            flexShrink: 0,
          }}
        >
          <button
            onClick={handleSave}
            disabled={createHabit.isPending || editHabit.isPending}
            style={{
              width: '100%',
              minHeight: '44px',
              backgroundColor: accent,
              border: 'none',
              borderRadius: '10px',
              color: '#FFFFFF',
              fontSize: typography.body.fontSize,
              fontFamily,
              fontWeight: 600,
              cursor: 'pointer',
              opacity: (createHabit.isPending || editHabit.isPending) ? 0.6 : 1,
            }}
          >
            {ctaLabel}
          </button>
          <button
            onMouseDown={(e) => e.preventDefault()}
            onClick={onClose}
            style={{
              width: '100%',
              minHeight: '36px',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              fontSize: typography.label.fontSize,
              fontFamily,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    </>
  )
}
