/**
 * DayDrilldownSheet.tsx — Per-slot meal breakdown for one day (D-16).
 *
 * Bottom sheet (phone) / centered modal (desktop) adapting TaskDetailSheet's
 * chrome: scrim zIndex 190, sheet zIndex 191, slide-up 250ms ease-out,
 * scroll-lock while open, and onMouseDown preventDefault on the close button
 * (the iOS blur-before-click trap). No text inputs → no keyboard-inset
 * tracking needed (plan: "bottom: 0, no keyboardInset").
 *
 * INVARIANT (CLAUDE.md §6, D-13/D-16, T-30-06-01): every row is labeled by
 * the fueling-slot NAME ("Breakfast"/"Post-lift"/…) — never a clock time.
 * The canonical slot timestamps never reach the wire and are never derived
 * or rendered here.
 *
 * Data contract: rows carry optional per-slot macros. The current
 * /api/health/nutrition response exposes day-level macro totals + a
 * slot-level hit matrix (no per-meal macro breakdown), so the page passes
 * slot rows without macros plus the server-computed day totals — both
 * rendered verbatim (T-30-06-02, no client re-derivation). When a future
 * backend plan adds per-slot macros, rows render the full UI-SPEC copy:
 * "{slot label} — {kcal} kcal, {protein}g protein, {carbs}g carbs,
 * {fat}g fat, {fiber}g fiber".
 */
import { useEffect, useState } from 'react'
import { GripHorizontal } from 'lucide-react'
import {
  border,
  secondary,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Macro totals rendered verbatim from the server (never re-derived client-side). */
export interface DayMacros {
  kcal: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  fiber_g: number | null
}

/** One per-slot row. `macros` is optional — see the data-contract note above. */
export interface DayDrilldownMeal {
  /** Canonical fueling-slot LABEL — never a clock time (CLAUDE.md §6). */
  slot_label: string
  macros?: DayMacros | null
}

interface DayDrilldownSheetProps {
  /** ISO date ("YYYY-MM-DD") of the day being drilled into. */
  date: string
  /** Slots with a logged meal that day, in slot order. Empty → empty-state copy. */
  meals: DayDrilldownMeal[]
  /** Server-computed macro totals for the whole day, rendered verbatim. */
  dayTotals?: DayMacros | null
  open: boolean
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Copy helpers
// ---------------------------------------------------------------------------

/**
 * UI-SPEC per-meal row macro string:
 * "{kcal} kcal, {protein}g protein, {carbs}g carbs, {fat}g fat, {fiber}g fiber"
 */
function formatMacros(m: DayMacros): string {
  const parts: string[] = []
  if (m.kcal !== null) parts.push(`${Math.round(m.kcal)} kcal`)
  if (m.protein_g !== null) parts.push(`${Math.round(m.protein_g)}g protein`)
  if (m.carbs_g !== null) parts.push(`${Math.round(m.carbs_g)}g carbs`)
  if (m.fat_g !== null) parts.push(`${Math.round(m.fat_g)}g fat`)
  if (m.fiber_g !== null) parts.push(`${Math.round(m.fiber_g)}g fiber`)
  return parts.join(', ')
}

// ---------------------------------------------------------------------------
// DayDrilldownSheet
// ---------------------------------------------------------------------------

export function DayDrilldownSheet({ date, meals, dayTotals, open, onClose }: DayDrilldownSheetProps) {
  const [slideIn, setSlideIn] = useState(false)

  // Slide-in animation (same requestAnimationFrame pattern as TaskDetailSheet).
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  // Lock background scroll while the sheet is open so iOS can't pan the
  // layout viewport (shows up as a horizontal shift on a fixed bottom sheet).
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open) return null

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768

  return (
    <>
      {/* Scrim — above BottomTabs (zIndex 100) so it covers the phone tab bar too */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(10,10,10,0.7)',
          zIndex: 190,
        }}
        aria-hidden="true"
      />

      {/* Sheet / Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${date} — Meals`}
        style={{
          position: 'fixed',
          zIndex: 191,
          ...(isPhone
            ? {
                // Phone: bottom sheet. No text inputs → no keyboard inset.
                left: 0,
                right: 0,
                bottom: 0,
                maxHeight: 'calc(100dvh - 24px)',
                borderRadius: '16px 16px 0 0',
                transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
                transition: 'transform 0.25s ease-out',
              }
            : {
                // Desktop: centered modal
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
        {/* Drag handle (phone) */}
        <div
          className="md:hidden"
          style={{
            display: 'flex',
            justifyContent: 'center',
            padding: '10px 0 4px',
          }}
          aria-hidden="true"
        >
          <GripHorizontal size={20} color={textSecondary} strokeWidth={2} />
        </div>

        {/* Title — "{date} — Meals" per 30-UI-SPEC Copywriting § Nutrition */}
        <h3
          style={{
            margin: 0,
            padding: '8px 16px 12px',
            fontSize: typography.body.fontSize,
            fontWeight: 600,
            lineHeight: typography.body.lineHeight,
            color: textPrimary,
            fontFamily,
            borderBottom: `1px solid ${border}`,
          }}
        >
          {date} — Meals
        </h3>

        {/* Body — scrollable */}
        <div
          style={{
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {meals.length === 0 ? (
            <p
              style={{
                margin: 0,
                fontSize: typography.label.fontSize,
                fontWeight: typography.label.fontWeight,
                lineHeight: typography.label.lineHeight,
                color: textSecondary,
                fontFamily,
                textAlign: 'center',
                padding: '16px 0',
              }}
            >
              No meals logged this day.
            </p>
          ) : (
            <>
              {meals.map((meal) => (
                <p
                  key={meal.slot_label}
                  style={{
                    margin: 0,
                    fontSize: typography.body.fontSize,
                    fontWeight: typography.body.fontWeight,
                    lineHeight: typography.body.lineHeight,
                    color: textPrimary,
                    fontFamily,
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{meal.slot_label}</span>
                  {' — '}
                  {meal.macros ? (
                    formatMacros(meal.macros)
                  ) : (
                    <span style={{ color: textSecondary }}>meal logged</span>
                  )}
                </p>
              ))}

              {dayTotals && (
                <p
                  style={{
                    margin: '6px 0 0',
                    paddingTop: '10px',
                    borderTop: `1px solid ${border}`,
                    fontSize: typography.label.fontSize,
                    fontWeight: typography.label.fontWeight,
                    lineHeight: typography.label.lineHeight,
                    color: textSecondary,
                    fontFamily,
                  }}
                >
                  <span style={{ color: textPrimary, fontWeight: 600 }}>Day total</span>
                  {' — '}
                  {formatMacros(dayTotals)}
                </p>
              )}
            </>
          )}
        </div>

        {/* Footer — close button. onMouseDown preventDefault avoids the iOS
            blur-before-click trap (mousedown blur eats the click). */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: `1px solid ${border}`,
            display: 'flex',
            justifyContent: 'flex-end',
            flexShrink: 0,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            onMouseDown={(e) => e.preventDefault()}
            style={{
              height: '44px',
              padding: '0 24px',
              border: `1px solid ${border}`,
              borderRadius: '10px',
              backgroundColor: 'transparent',
              color: textPrimary,
              fontSize: typography.body.fontSize,
              fontFamily,
              cursor: 'pointer',
              ...(isPhone ? { width: '100%' } : {}),
            }}
          >
            Close
          </button>
        </div>
      </div>
    </>
  )
}
