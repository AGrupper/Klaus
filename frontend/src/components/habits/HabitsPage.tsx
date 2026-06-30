/**
 * HabitsPage.tsx — Root /habits route component (HABIT-01, HABIT-02).
 *
 * Phone layout (< 768px):
 *   BottomTabs tabs nav + scrollable slot-grouped HabitRows
 *   + FAB (phone-only, 56px accent, above BottomTabs)
 *
 * Desktop layout (≥ 768px):
 *   Single main content column (flat list, can add sidebar later)
 *
 * Slot groups: Morning → Noon → Evening → Bedtime (sticky headers on phone)
 *
 * Display rule (T-28-display, Pitfall 2): the phone-only FAB wrapper MUST use
 * `className="md:hidden"` — never `style={{ display }}` (would override Tailwind).
 *
 * State management:
 *   - editHabit/editOpen: which habit is in HabitCreateEditSheet (null = create mode)
 *   - doseHabit/doseOpen: which supplement is in DoseEditSheet
 *   - detailHabit/detailOpen: which habit is in HabitDetailView (wired in Task 3)
 *
 * UndoToast is rendered in TasksPage; HabitsPage re-uses the same global UndoToast.
 *
 * Security (T-28-xss): all habit content rendered via HabitRow as plain text.
 */
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useHabits, useSoftDeleteHabit } from '../../hooks/useHabits'
import { useUndoStore } from '../../store/undoStore'
import { hardDeleteHabit } from '../../api/habits'
import { HabitRow } from './HabitRow'
import { HabitCreateEditSheet } from './HabitCreateEditSheet'
import { DoseEditSheet } from './DoseEditSheet'
import { HabitDetailView } from './HabitDetailView'
import type { Habit, HabitSlot } from '../../api/habits'
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
// Constants
// ---------------------------------------------------------------------------

const SLOT_ORDER: HabitSlot[] = ['Morning', 'Noon', 'Evening', 'Bedtime']

// ---------------------------------------------------------------------------
// Group habits by slot
// ---------------------------------------------------------------------------

function groupBySlot(habits: Habit[]): Record<HabitSlot, Habit[]> {
  const groups: Record<HabitSlot, Habit[]> = {
    Morning: [],
    Noon: [],
    Evening: [],
    Bedtime: [],
  }
  for (const h of habits) {
    if (groups[h.slot]) {
      groups[h.slot].push(h)
    }
  }
  return groups
}

// ---------------------------------------------------------------------------
// HabitsPage
// ---------------------------------------------------------------------------

export function HabitsPage() {
  const { data: habits = [], isLoading, isError } = useHabits()
  const softDeleteMutation = useSoftDeleteHabit()
  const undoShow = useUndoStore((s) => s.show)
  const undoActiveItem = useUndoStore((s) => s.activeItem)

  // Edit sheet state (null = create mode)
  const [editHabit, setEditHabit] = useState<Habit | null>(null)
  const [editOpen, setEditOpen] = useState(false)

  // Dose edit sheet state (supplement check-off, D-09)
  const [doseHabit, setDoseHabit] = useState<Habit | null>(null)
  const [doseOpen, setDoseOpen] = useState(false)

  // Detail view state (HabitDetailView wired in Task 3 / HabitDetailView.tsx)
  const [detailHabit, setDetailHabit] = useState<Habit | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function openCreate() {
    setEditHabit(null)
    setEditOpen(true)
  }

  function openEdit(habit: Habit) {
    setEditHabit(habit)
    setEditOpen(true)
  }

  function openDetail(habit: Habit) {
    setDetailHabit(habit)
    setDetailOpen(true)
  }

  function openDose(habit: Habit) {
    setDoseHabit(habit)
    setDoseOpen(true)
  }

  function handleDelete(habit: Habit) {
    // Replace any existing undo item
    if (undoActiveItem && undoActiveItem.id !== habit.id) {
      if (undoActiveItem.resourceType === 'habit') {
        hardDeleteHabit(undoActiveItem.id).catch(() => {})
      }
    }

    softDeleteMutation.mutate(
      { id: habit.id },
      {
        onSuccess: () => {
          undoShow({
            id: habit.id,
            action: 'delete',
            listId: 'habits',
            nextId: null,
            resourceType: 'habit',
          })
          // Close detail view if the deleted habit was open there
          if (detailHabit?.id === habit.id) {
            setDetailOpen(false)
          }
        },
      },
    )
  }

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  const grouped = groupBySlot(habits)

  const hasAnyHabits = habits.length > 0

  return (
    <>
      {/* Main layout */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          overflow: 'hidden',
          backgroundColor: dominant,
        }}
      >
        {/* Page title header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            height: '52px',
            padding: '0 16px',
            borderBottom: `1px solid ${border}`,
            backgroundColor: secondary,
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontSize: typography.heading.fontSize,
              fontWeight: typography.heading.fontWeight,
              fontFamily,
              color: textPrimary,
            }}
          >
            Habits
          </span>
        </div>

        {/* Content area */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
          {/* Loading state */}
          {isLoading && (
            <div
              style={{
                padding: '32px 16px',
                textAlign: 'center',
                color: textSecondary,
                fontSize: typography.body.fontSize,
                fontFamily,
              }}
            >
              Loading habits…
            </div>
          )}

          {/* Error state */}
          {isError && (
            <div
              style={{
                padding: '32px 16px',
                textAlign: 'center',
                color: textSecondary,
                fontSize: typography.body.fontSize,
                fontFamily,
              }}
            >
              Couldn't load habits — pull to refresh.
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !isError && !hasAnyHabits && (
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '48px 24px',
                gap: '8px',
              }}
            >
              <span
                style={{
                  fontSize: typography.heading.fontSize,
                  fontWeight: typography.heading.fontWeight,
                  fontFamily,
                  color: textPrimary,
                  textAlign: 'center',
                }}
              >
                No habits yet
              </span>
              <span
                style={{
                  fontSize: typography.body.fontSize,
                  fontFamily,
                  color: textSecondary,
                  textAlign: 'center',
                }}
              >
                Add your first habit or supplement to start tracking.
              </span>
              {/* Desktop CTA (FAB is phone-only) */}
              <div className="hidden md:block" style={{ marginTop: '16px' }}>
                <button
                  onClick={openCreate}
                  style={{
                    minHeight: '44px',
                    padding: '0 24px',
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
                  Add habit
                </button>
              </div>
            </div>
          )}

          {/* Slot-grouped habit list */}
          {!isLoading && !isError && hasAnyHabits && (
            <div>
              {SLOT_ORDER.map((slot) => {
                const slotHabits = grouped[slot]
                if (slotHabits.length === 0) return null
                return (
                  <div key={slot}>
                    {/* Slot group header — sticky, Label 13px uppercase textSecondary */}
                    <div
                      style={{
                        position: 'sticky',
                        top: 0,
                        backgroundColor: dominant,  // #0A0A0A — same as page bg to prevent bleed
                        zIndex: 10,
                        padding: '10px 16px 6px',
                        color: textSecondary,
                        fontSize: typography.label.fontSize,
                        fontFamily,
                        fontWeight: typography.label.fontWeight,
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                      }}
                    >
                      {slot}
                    </div>

                    {/* Habits in this slot */}
                    {slotHabits.map((habit) => (
                      <HabitRow
                        key={habit.id}
                        habit={habit}
                        onOpenDetail={openDetail}
                        onOpenEdit={openEdit}
                        onOpenDose={openDose}
                        onDelete={handleDelete}
                      />
                    ))}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Phone FAB — class-driven display (md:hidden), NEVER inline style={{ display }}.
            This is the Pitfall 2 / T-28-display critical guard. */}
        <div className="md:hidden">
          <button
            onClick={openCreate}
            aria-label="Add habit"
            style={{
              position: 'fixed',
              right: '16px',
              bottom: 'calc(env(safe-area-inset-bottom, 0px) + 76px)',
              width: '56px',
              height: '56px',
              borderRadius: '28px',
              backgroundColor: accent,
              border: 'none',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              boxShadow: '0 4px 16px rgba(99,102,241,0.5)',
              zIndex: 40,
            }}
          >
            <Plus size={24} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>

        {/* Desktop "Add habit" button in the header (phone uses FAB) */}
        <div
          className="hidden md:block"
          style={{ position: 'absolute', top: '10px', right: '16px', zIndex: 20 }}
        >
          <button
            onClick={openCreate}
            style={{
              minHeight: '36px',
              padding: '0 16px',
              backgroundColor: accent,
              border: 'none',
              borderRadius: '8px',
              color: '#FFFFFF',
              fontSize: typography.label.fontSize,
              fontFamily,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Add habit
          </button>
        </div>
      </div>

      {/* Create / Edit sheet */}
      <HabitCreateEditSheet
        habit={editHabit}
        open={editOpen}
        onClose={() => setEditOpen(false)}
      />

      {/* Dose edit sheet (supplement check-off, D-09) */}
      <DoseEditSheet
        habit={doseHabit}
        open={doseOpen}
        onClose={() => setDoseOpen(false)}
      />

      {/* HabitDetailView — per-habit 365-day grid, streak, and Edit/Delete footer (HABIT-04). */}
      <HabitDetailView
        habit={detailHabit}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onEdit={(h) => { setDetailOpen(false); openEdit(h) }}
        onDelete={handleDelete}
      />
    </>
  )
}
