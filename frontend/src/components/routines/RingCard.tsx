/**
 * RingCard.tsx — one routine as a filling ring (the mockup-gate winner).
 *
 * The SVG ring fills as scheduled members get checked; the flame badge pops
 * (flamepop keyframes) the moment done_today flips true. Checkbox taps are
 * optimistic via useCheckinMember; tapping a member's name opens its edit
 * sheet; the pencil opens the routine's own edit sheet.
 */
import { useEffect, useRef, useState } from 'react'
import { Check, Pencil, Plus } from 'lucide-react'
import type { Routine, RoutineMember } from '../../api/routines'
import { useCheckinMember } from '../../hooks/useRoutines'

const RING_RADIUS = 32
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS // ≈ 201

interface RingCardProps {
  routine: Routine
  todayIso: string
  onEditRoutine: (routine: Routine) => void
  onEditHabit: (habit: RoutineMember) => void
  onAddHabit: (routine: Routine) => void
}

export function RingCard({ routine, todayIso, onEditRoutine, onEditHabit, onAddHabit }: RingCardProps) {
  const checkin = useCheckinMember()

  // Flame pop on completion: fires when done_today transitions false → true.
  const [pop, setPop] = useState(false)
  const wasDone = useRef(routine.done_today)
  useEffect(() => {
    if (routine.done_today && !wasDone.current) {
      setPop(true)
      const id = setTimeout(() => setPop(false), 500)
      return () => clearTimeout(id)
    }
    wasDone.current = routine.done_today
    return undefined
  }, [routine.done_today])
  useEffect(() => {
    wasDone.current = routine.done_today
  }, [routine.done_today])

  const scheduled = routine.habits.filter((h) => h.scheduled_today)
  const total = scheduled.length
  const done = routine.completed_today
  const offset = total > 0 ? RING_CIRCUMFERENCE * (1 - done / total) : RING_CIRCUMFERENCE

  return (
    <div
      style={{
        background: 'var(--surface)',
        borderRadius: 'var(--r)',
        padding: '16px 14px',
        display: 'flex',
        gap: '14px',
        alignItems: 'flex-start',
        margin: '0 20px 12px',
      }}
    >
      <svg width="76" height="76" viewBox="0 0 76 76" aria-hidden="true" style={{ flexShrink: 0 }}>
        <circle cx="38" cy="38" r={RING_RADIUS} fill="none" strokeWidth="7" stroke="var(--sep)" />
        <circle
          cx="38"
          cy="38"
          r={RING_RADIUS}
          fill="none"
          strokeWidth="7"
          stroke="var(--flame)"
          strokeLinecap="round"
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
          transform="rotate(-90 38 38)"
          style={{ transition: 'stroke-dashoffset 0.5s cubic-bezier(0.3,0.8,0.3,1)' }}
        />
        <text
          x="38"
          y="43"
          textAnchor="middle"
          fontSize="15"
          fontWeight="700"
          fill="var(--ink)"
          style={{ fontFamily: 'var(--font-display)', fontVariantNumeric: 'tabular-nums' }}
        >
          {total > 0 ? `${done}/${total}` : '—'}
        </text>
      </svg>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '7px' }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              letterSpacing: '-0.02em',
              fontSize: '17px',
              color: 'var(--ink)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {routine.emoji ? `${routine.emoji} ` : ''}
            {routine.name}
          </span>
          {routine.id !== null && (
            <button
              onClick={() => onEditRoutine(routine)}
              aria-label={`Edit ${routine.name}`}
              style={{
                border: 'none',
                background: 'none',
                color: 'var(--faint)',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
              }}
            >
              <Pencil size={13} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
          <span
            className={pop ? 'flame-pop' : undefined}
            style={{
              marginLeft: 'auto',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--flame-soft)',
              color: 'var(--flame)',
              borderRadius: '999px',
              padding: '3px 9px',
              fontSize: '12.5px',
              fontWeight: 700,
              fontVariantNumeric: 'tabular-nums',
              animation: pop ? 'flamepop 0.45s ease' : undefined,
            }}
          >
            🔥 {routine.streak}
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {routine.habits.length === 0 && (
            <span style={{ fontSize: '13.5px', color: 'var(--muted)' }}>No items yet.</span>
          )}
          {routine.habits.map((habit) => {
            const inactive = !habit.scheduled_today
            return (
              <div key={habit.id} style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
                <button
                  onClick={() =>
                    checkin.mutate({ habitId: habit.id, date: todayIso, done: !habit.done_today })
                  }
                  disabled={inactive}
                  aria-label={`${habit.done_today ? 'Uncheck' : 'Check off'} ${habit.name}`}
                  aria-pressed={habit.done_today}
                  style={{
                    width: '21px',
                    height: '21px',
                    borderRadius: '50%',
                    flexShrink: 0,
                    border: `1.5px solid ${habit.done_today ? 'var(--flame)' : 'var(--faint)'}`,
                    background: habit.done_today ? 'var(--flame)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: inactive ? 'default' : 'pointer',
                    opacity: inactive ? 0.35 : 1,
                    transition: 'background 0.18s, border-color 0.18s',
                    padding: 0,
                  }}
                >
                  {habit.done_today && (
                    <Check size={12} color="#FFFFFF" strokeWidth={3.5} aria-hidden="true" />
                  )}
                </button>
                <button
                  onClick={() => onEditHabit(habit)}
                  style={{
                    border: 'none',
                    background: 'none',
                    padding: '3px 0',
                    fontSize: '14.5px',
                    textAlign: 'left',
                    cursor: 'pointer',
                    color: habit.done_today ? 'var(--faint)' : 'var(--ink)',
                    textDecoration: habit.done_today ? 'line-through' : 'none',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    minWidth: 0,
                    flex: 1,
                  }}
                >
                  {habit.name}
                  {habit.dose && (
                    <span style={{ color: 'var(--muted)', fontWeight: 400 }}> · {habit.dose}</span>
                  )}
                  {inactive && (
                    <span style={{ color: 'var(--faint)', fontWeight: 400 }}> · not today</span>
                  )}
                </button>
              </div>
            )
          })}
          <button
            onClick={() => onAddHabit(routine)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              border: 'none',
              background: 'none',
              color: 'var(--muted)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              padding: '4px 0 0',
            }}
          >
            <Plus size={14} strokeWidth={2.2} aria-hidden="true" />
            Add item
          </button>
        </div>
      </div>
    </div>
  )
}
