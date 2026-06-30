/**
 * HabitDetailView.tsx — Per-habit detail bottom sheet (phone) / centered modal (desktop).
 *
 * Shows the 365-day ContributionGrid, streak, slot, dose (supplements), a four-state
 * legend, and Edit / Delete footer buttons.
 *
 * iOS safety (Phase 26/27 lessons — MANDATORY):
 *   - Scrim z:190 / sheet z:191 (beats BottomTabs z:100)
 *   - useVisualViewport keyboardInset to anchor sheet above iOS soft keyboard
 *   - scroll-lock: document.body.style.overflow = 'hidden' while open
 *   - NO autoFocus on phone (iOS layout-pan trap; no focused input here anyway)
 *   - onMouseDown={e => e.preventDefault()} on scrim and dismiss/destructive buttons
 *     to prevent blur-before-click eating any active input in a lower sheet
 *
 * Display rule (T-28-display, Pitfall 2): class-driven show/hide only.
 *   Drag handle: className="md:hidden" — NEVER inline style={{ display }}.
 *
 * Security (T-28-xss): habit.name, habit.dose, habit.slot rendered as plain React
 * text children — no dangerouslySetInnerHTML anywhere in this file.
 *
 * Color rule: every color comes from tokens.ts except the grid-state `missed` fill
 * (#3A1A1A), which is imported from ContributionGrid.tsx (not repeated here).
 */
import { useState, useEffect } from 'react'
import { GripHorizontal } from 'lucide-react'
import { useHabitHistory } from '../../hooks/useHabits'
import { useVisualViewport } from '../../hooks/useVisualViewport'
import { ContributionGrid, CELL_COLORS } from './ContributionGrid'
import type { Habit, GridState } from '../../api/habits'
import {
  accent,
  border,
  destructive,
  secondary,
  skeleton,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HabitDetailViewProps {
  /** null → view is closed (open=false takes effect via early return anyway) */
  habit: Habit | null
  open: boolean
  onClose: () => void
  /** Footer "Edit" button → open HabitCreateEditSheet for this habit */
  onEdit: (habit: Habit) => void
  /** Footer "Delete habit" button → soft-delete + undo toast flow */
  onDelete: (habit: Habit) => void
}

// ---------------------------------------------------------------------------
// Legend data
// ---------------------------------------------------------------------------

const LEGEND_ITEMS: Array<{ state: GridState; label: string }> = [
  { state: 'done', label: 'Done' },
  { state: 'missed', label: 'Missed' },
  { state: 'not-scheduled', label: 'Not scheduled' },
  { state: 'pending', label: 'Pending' },
]

// ---------------------------------------------------------------------------
// SlotChip (local — mirrors HabitRow's SlotChip)
// ---------------------------------------------------------------------------

function SlotChip({ slot }: { slot: string }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 8px',
        borderRadius: '6px',
        backgroundColor: border,   // #2A2A2A
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
// HabitDetailView
// ---------------------------------------------------------------------------

export function HabitDetailView({
  habit,
  open,
  onClose,
  onEdit,
  onDelete,
}: HabitDetailViewProps) {
  // Fetch per-habit 365-day grid + streak (HABIT-04)
  const { data: history, isLoading: historyLoading } = useHabitHistory(habit?.id ?? '')

  const { keyboardInset } = useVisualViewport()
  const [slideIn, setSlideIn] = useState(false)

  // Slide-in animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  // Scroll lock while open (prevents iOS layout pan and background scroll)
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  // Early return — TypeScript narrows `habit` to non-null below this point
  if (!open || !habit) return null

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768

  // Prefer the history endpoint's streak; fall back to enriched list field
  const streak = history?.streak ?? habit.streak ?? 0
  const cells = history?.grid ?? []

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
        aria-label={`${habit.name} details`}
        style={{
          position: 'fixed',
          zIndex: 191,
          // Phone: slide up from bottom, track keyboard inset
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
                // Desktop: centered modal, max 480px
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
        {/* Drag handle — phone only, class-driven display (md:hidden, NOT inline style) */}
        <div
          className="md:hidden"
          style={{ display: 'flex', justifyContent: 'center', padding: '10px 0 4px' }}
          aria-hidden="true"
        >
          <GripHorizontal size={20} color={textSecondary} strokeWidth={2} />
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Body — scrollable                                                 */}
        {/* ---------------------------------------------------------------- */}
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
          {/* Habit name — Heading 20px/600 textPrimary */}
          <h2
            style={{
              margin: 0,
              fontSize: typography.heading.fontSize,
              fontWeight: typography.heading.fontWeight,
              fontFamily,
              color: textPrimary,
              lineHeight: typography.heading.lineHeight,
            }}
          >
            {habit.name}
          </h2>

          {/* Slot chip + streak value — Label 13px textSecondary */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
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
                {streak}-day streak
              </span>
            )}
          </div>

          {/* Dose — supplement only, Label 13px textSecondary */}
          {habit.type === 'supplement' && habit.dose && (
            <span
              style={{
                fontSize: typography.label.fontSize,
                fontFamily,
                color: textSecondary,
              }}
            >
              {habit.dose}
            </span>
          )}

          {/* "HISTORY" section heading — Label 13px textSecondary uppercase */}
          <span
            style={{
              fontSize: typography.label.fontSize,
              fontFamily,
              color: textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
            }}
          >
            History
          </span>

          {/* Contribution grid (or loading/empty state) */}
          {historyLoading ? (
            /* Skeleton placeholder while history loads */
            <div
              role="status"
              aria-label="Loading history…"
              style={{
                height: '100px',
                backgroundColor: skeleton,
                borderRadius: '6px',
              }}
            />
          ) : cells.length > 0 ? (
            <ContributionGrid cells={cells} />
          ) : (
            /* Empty grid state — exact 28-UI-SPEC copy */
            <span
              style={{
                fontSize: typography.label.fontSize,
                fontFamily,
                color: textSecondary,
              }}
            >
              Not enough data yet — check off days to build your history.
            </span>
          )}

          {/* Four-state legend */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '8px 16px',
            }}
          >
            {LEGEND_ITEMS.map(({ state, label }) => (
              <div
                key={state}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <div
                  aria-hidden="true"
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: CELL_COLORS[state],
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    color: textSecondary,
                  }}
                >
                  {label}
                </span>
              </div>
            ))}
          </div>

          {/* Streak label — exact 28-UI-SPEC copy */}
          <span
            style={{
              fontSize: typography.label.fontSize,
              fontFamily,
              color: textSecondary,
            }}
          >
            {streak > 0
              ? `${streak}-day streak`
              : 'No streak — check off today to start one.'}
          </span>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Footer — Edit + Delete habit                                      */}
        {/* ---------------------------------------------------------------- */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: `1px solid ${border}`,
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            paddingBottom: isPhone
              ? 'calc(env(safe-area-inset-bottom, 0px) + 12px)'
              : '12px',
            flexShrink: 0,
          }}
        >
          {/* Edit — accent CTA */}
          <button
            onClick={() => {
              onClose()
              onEdit(habit)
            }}
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
            }}
          >
            Edit
          </button>

          {/* Delete habit — destructive text button; onMouseDown preventDefault
              prevents blur-before-click eating the tap on iOS */}
          <button
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              onClose()
              onDelete(habit)
            }}
            style={{
              width: '100%',
              minHeight: '36px',
              border: 'none',
              backgroundColor: 'transparent',
              color: destructive,   // #EF4444
              fontSize: typography.label.fontSize,
              fontFamily,
              cursor: 'pointer',
            }}
          >
            Delete habit
          </button>
        </div>
      </div>
    </>
  )
}
