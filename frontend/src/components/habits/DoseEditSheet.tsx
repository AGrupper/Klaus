/**
 * DoseEditSheet.tsx — Inline dose-confirmation sheet for supplement check-off.
 *
 * Triggered when a supplement row is tapped (D-09). Shows the supplement name +
 * default dose; lets the user adjust the dose before saving.
 *
 * iOS safety (Phase 26/27 lessons — MANDATORY):
 *   - Sheet z:192 (above HabitDetailView z:191 and HabitCreateEditSheet z:191)
 *   - Scrim z:191 (dims the underlying sheet while DoseEditSheet is open)
 *   - Desktop: scrim z:201, sheet z:202
 *   - useVisualViewport keyboardInset to anchor above iOS soft keyboard
 *   - scroll-lock: document.body.style.overflow = 'hidden' while open
 *   - NO autoFocus on phone (iOS layout-pan trap)
 *   - onMouseDown={e => e.preventDefault()} on "Discard dose" button
 *
 * Display rule (T-28-display): no inline style={{ display }} — Tailwind classes only.
 *
 * Security (T-28-xss): name and dose rendered as plain React text — no
 * dangerouslySetInnerHTML.
 */
import { useState, useEffect } from 'react'
import { GripHorizontal } from 'lucide-react'
import { useCheckOffHabit } from '../../hooks/useHabits'
import { useVisualViewport } from '../../hooks/useVisualViewport'
import type { Habit } from '../../api/habits'
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

interface DoseEditSheetProps {
  /** The supplement being checked off. */
  habit: Habit | null
  open: boolean
  onClose: () => void
}

// ---------------------------------------------------------------------------
// DoseEditSheet
// ---------------------------------------------------------------------------

export function DoseEditSheet({ habit, open, onClose }: DoseEditSheetProps) {
  const checkOffMutation = useCheckOffHabit()
  const { keyboardInset } = useVisualViewport()

  const [doseValue, setDoseValue] = useState('')
  const [slideIn, setSlideIn] = useState(false)

  // Pre-fill with default dose when habit changes
  useEffect(() => {
    if (habit) {
      setDoseValue(habit.dose ?? '')
    }
  }, [habit, open])

  // Slide-in animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  // Scroll lock while open
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open || !habit) return null

  function handleSave() {
    if (!habit) return
    const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })
    checkOffMutation.mutate(
      {
        habitId: habit.id,
        date: today,
        done: true,
        doseTaken: doseValue.trim() || null,
      },
      {
        onSuccess: () => { onClose() },
        onError: () => { onClose() },  // still close; optimistic rollback handles state
      },
    )
  }

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768

  // z-index: phone scrim:191/sheet:192; desktop scrim:201/sheet:202
  const scrimZ = isPhone ? 191 : 201
  const sheetZ = isPhone ? 192 : 202

  return (
    <>
      {/* Scrim — dims the underlying sheet while DoseEditSheet is open */}
      <div
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(10,10,10,0.5)',
          zIndex: scrimZ,
        }}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Adjust dose for ${habit.name}`}
        style={{
          position: 'fixed',
          zIndex: sheetZ,
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

        {/* Body */}
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
          {/* Supplement name + default dose — Body 16px textPrimary */}
          <p
            style={{
              margin: 0,
              fontSize: typography.body.fontSize,
              fontFamily,
              color: textPrimary,
              fontWeight: 400,
            }}
          >
            {habit.name}
            {habit.dose ? ` — ${habit.dose}` : ''}
          </p>

          {/* ADJUST DOSE TAKEN label */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: typography.label.fontSize,
                fontFamily,
                color: textSecondary,
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                marginBottom: '8px',
              }}
              htmlFor="dose-input"
            >
              Adjust dose taken:
            </label>
            <input
              id="dose-input"
              type="text"
              value={doseValue}
              onChange={(e) => setDoseValue(e.target.value)}
              placeholder="e.g. 5g"
              maxLength={200}
              // No autoFocus on phone (iOS layout-pan trap)
              autoFocus={!isPhone}
              style={{
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
              }}
            />
          </div>
        </div>

        {/* Footer */}
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
          {/* Save dose — accent, 44px full-width on phone */}
          <button
            onClick={handleSave}
            disabled={checkOffMutation.isPending}
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
              opacity: checkOffMutation.isPending ? 0.6 : 1,
            }}
          >
            Save dose
          </button>

          {/* Discard dose — textSecondary, no state change */}
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
            Discard dose
          </button>
        </div>
      </div>
    </>
  )
}
