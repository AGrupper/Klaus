/**
 * RoutinesPage.tssx — /routines: ring cards, one per routine, + creation.
 *
 * The header line reflects live state (how many flames, what's left tonight).
 * Sheets: RoutineEditSheet (create/edit group), HabitEditSheet (create/edit
 * member). Check-ins happen inline on the cards.
 */
import { useState } from 'react'
import { Plus } from 'lucide-react'
import type { Habit } from '../../api/habits'
import type { Routine, RoutineMember } from '../../api/routines'
import { useRoutines } from '../../hooks/useRoutines'
import { RingCard } from './RingCard'
import { RoutineEditSheet } from './RoutineEditSheet'
import { HabitEditSheet } from './HabitEditSheet'

function todayIsoJerusalem(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jerusalem' }).format(new Date())
}

function headline(routines: Routine[]): { title: string; sub: string } {
  const flames = routines.filter((r) => r.streak > 0).length
  const pending = routines.filter((r) => r.scheduled_today > 0 && !r.done_today)
  if (routines.length === 0) {
    return { title: 'No routines yet.', sub: 'Create one and start a flame.' }
  }
  if (pending.length === 0) {
    return { title: 'All done for today.', sub: 'Every flame is safe, Sir.' }
  }
  const flameWord = flames === 1 ? 'One flame alive' : `${flames} flames alive`
  return {
    title: flames > 0 ? `${flameWord}.` : 'Routines.',
    sub: `${pending.length} routine${pending.length === 1 ? '' : 's'} still open today.`,
  }
}

export function RoutinesPage() {
  const { data: routines = [], isLoading, isError } = useRoutines()
  const todayIso = todayIsoJerusalem()

  const [editRoutine, setEditRoutine] = useState<Routine | null>(null)
  const [routineSheetOpen, setRoutineSheetOpen] = useState(false)
  const [editHabit, setEditHabit] = useState<Habit | null>(null)
  const [targetRoutine, setTargetRoutine] = useState<Routine | null>(null)
  const [habitSheetOpen, setHabitSheetOpen] = useState(false)

  const { title, sub } = headline(routines)

  return (
    <div style={{ paddingBottom: '24px' }}>
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          fontSize: '28px',
          lineHeight: 1.12,
          margin: '12px 20px 3px',
          color: 'var(--ink)',
          textWrap: 'balance',
        }}
      >
        {title}
      </h1>
      <p style={{ margin: '0 20px 18px', color: 'var(--muted)', fontSize: '14px' }}>{sub}</p>

      {isLoading && (
        <div style={{ margin: '0 20px', color: 'var(--muted)', fontSize: '14px' }}>Loading routines…</div>
      )}
      {isError && (
        <div style={{ margin: '0 20px', color: 'var(--muted)', fontSize: '14px' }}>
          Couldn't load routines — check your connection.
        </div>
      )}

      {routines.map((routine) => (
        <RingCard
          key={routine.id ?? 'unassigned'}
          routine={routine}
          todayIso={todayIso}
          onEditRoutine={(r) => {
            setEditRoutine(r)
            setRoutineSheetOpen(true)
          }}
          onEditHabit={(habit: RoutineMember) => {
            setEditHabit(habit)
            setTargetRoutine(routine)
            setHabitSheetOpen(true)
          }}
          onAddHabit={(r) => {
            setEditHabit(null)
            setTargetRoutine(r)
            setHabitSheetOpen(true)
          }}
        />
      ))}

      <div style={{ margin: '4px 20px' }}>
        <button
          onClick={() => {
            setEditRoutine(null)
            setRoutineSheetOpen(true)
          }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '7px',
            minHeight: '44px',
            padding: '0 18px',
            border: 'none',
            borderRadius: '12px',
            background: 'var(--surface)',
            color: 'var(--accent)',
            fontSize: '14.5px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          <Plus size={16} strokeWidth={2.2} aria-hidden="true" />
          New routine
        </button>
      </div>

      <RoutineEditSheet
        routine={editRoutine}
        open={routineSheetOpen}
        onClose={() => setRoutineSheetOpen(false)}
      />
      <HabitEditSheet
        habit={editHabit}
        targetRoutine={targetRoutine}
        routines={routines}
        open={habitSheetOpen}
        onClose={() => setHabitSheetOpen(false)}
      />
    </div>
  )
}
