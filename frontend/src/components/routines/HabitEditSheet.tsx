/**
 * HabitEditSheet.tsx — create or edit a habit/supplement inside a routine.
 *
 * Fields: name · dose (marks it a supplement when set) · routine · days.
 * Schedule edits append a forward-only revision server-side (D-19); deletes
 * go through soft-delete + the global UndoToast (D-20).
 *
 * All content is plain text in/out — never HTML (T-28-xss).
 */
import { useEffect, useState } from 'react'
import type { Habit } from '../../api/habits'
import { createHabit, editHabit } from '../../api/habits'
import type { Routine } from '../../api/routines'
import { useQueryClient } from '@tanstack/react-query'
import { useMutation } from '@tanstack/react-query'
import { useSoftDeleteHabit } from '../../hooks/useHabits'
import { useUndoStore } from '../../store/undoStore'

import { Sheet } from '../shared/Sheet'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] // Python weekday ints Mon=0

const inputStyle: React.CSSProperties = {
  width: '100%',
  border: 'none',
  background: 'var(--surface)',
  borderRadius: '10px',
  padding: '12px 14px',
  fontSize: '16px', // ≥16px prevents iOS Safari zoom-on-focus
  color: 'var(--ink)',
  outline: 'none',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '11px',
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'var(--muted)',
  fontWeight: 600,
  margin: '14px 0 8px',
}

interface HabitEditSheetProps {
  /** null = create mode (targetRoutine seeds the routine picker). */
  habit: Habit | null
  targetRoutine: Routine | null
  routines: Routine[]
  open: boolean
  onClose: () => void
}

export function HabitEditSheet({ habit, targetRoutine, routines, open, onClose }: HabitEditSheetProps) {
  const queryClient = useQueryClient()
  const softDelete = useSoftDeleteHabit()
  const undoShow = useUndoStore((s) => s.show)

  const [name, setName] = useState('')
  const [dose, setDose] = useState('')
  const [routineId, setRoutineId] = useState<string | ''>('')
  const [daily, setDaily] = useState(true)
  const [days, setDays] = useState<number[]>([])

  useEffect(() => {
    if (!open) return
    setName(habit?.name ?? '')
    setDose(habit?.dose ?? '')
    setRoutineId(habit?.routine_id ?? targetRoutine?.id ?? '')
    const history = habit?.schedule_history ?? []
    const currentDays = history.length > 0 ? history[history.length - 1].days : 'daily'
    if (currentDays === 'daily') {
      setDaily(true)
      setDays([])
    } else {
      setDaily(false)
      setDays(Array.isArray(currentDays) ? currentDays : [])
    }
  }, [open, habit, targetRoutine])

  const editing = habit !== null
  const canSave = name.trim().length > 0 && (daily || days.length > 0)

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['routines'] })
    void queryClient.invalidateQueries({ queryKey: ['habits'] })
  }

  const save = useMutation({
    mutationFn: async () => {
      const schedule = daily ? ('daily' as const) : [...days].sort()
      const payload = {
        name: name.trim(),
        dose: dose.trim() || null,
        type: (dose.trim() ? 'supplement' : 'habit') as Habit['type'],
        routine_id: routineId || null,
        days: schedule,
      }
      if (editing && habit) {
        await editHabit(habit.id, payload)
      } else {
        await createHabit(payload)
      }
    },
    onSettled: invalidate,
  })

  function handleSave() {
    if (!canSave) return
    save.mutate()
    onClose()
  }

  function handleDelete() {
    if (!editing || !habit) return
    softDelete.mutate(
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
          invalidate()
        },
      },
    )
    onClose()
  }

  function toggleDay(day: number) {
    setDays((current) =>
      current.includes(day) ? current.filter((d) => d !== day) : [...current, day],
    )
  }

  return (
    <Sheet open={open} onClose={onClose} title={editing ? 'Edit item' : 'New item'}>
      <label style={labelStyle} htmlFor="habit-name">Name</label>
      <input
        id="habit-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Creatine"
        maxLength={500}
        style={inputStyle}
      />

      <label style={labelStyle} htmlFor="habit-dose">Dose (optional — makes it a supplement)</label>
      <input
        id="habit-dose"
        value={dose}
        onChange={(e) => setDose(e.target.value)}
        placeholder="5 g"
        maxLength={200}
        style={inputStyle}
      />

      <label style={labelStyle} htmlFor="habit-routine">Routine</label>
      <select
        id="habit-routine"
        value={routineId}
        onChange={(e) => setRoutineId(e.target.value)}
        style={{ ...inputStyle, appearance: 'none' }}
      >
        <option value="">Unassigned</option>
        {routines
          .filter((r): r is Routine & { id: string } => r.id !== null)
          .map((r) => (
            <option key={r.id} value={r.id}>
              {r.emoji ? `${r.emoji} ` : ''}{r.name}
            </option>
          ))}
      </select>

      <span style={labelStyle}>Days</span>
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
        <button
          onClick={() => setDaily(true)}
          aria-pressed={daily}
          style={{
            border: 'none',
            borderRadius: '999px',
            padding: '8px 14px',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            background: daily ? 'var(--accent)' : 'var(--surface)',
            color: daily ? 'var(--accent-ink)' : 'var(--muted)',
          }}
        >
          Every day
        </button>
        {WEEKDAYS.map((label, day) => {
          const on = !daily && days.includes(day)
          return (
            <button
              key={label}
              onClick={() => {
                setDaily(false)
                toggleDay(day)
              }}
              aria-pressed={on}
              style={{
                border: 'none',
                borderRadius: '999px',
                padding: '8px 12px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                background: on ? 'var(--accent)' : 'var(--surface)',
                color: on ? 'var(--accent-ink)' : 'var(--muted)',
              }}
            >
              {label}
            </button>
          )
        })}
      </div>
      {editing && (
        <p style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '8px', lineHeight: 1.5 }}>
          Schedule changes apply from today forward — history stays as it was.
        </p>
      )}

      <div style={{ display: 'flex', gap: '10px', margin: '20px 0 6px' }}>
        <button
          onClick={handleSave}
          disabled={!canSave}
          style={{
            flex: 1,
            minHeight: '46px',
            border: 'none',
            borderRadius: '12px',
            background: 'var(--accent)',
            color: 'var(--accent-ink)',
            fontSize: '15.5px',
            fontWeight: 600,
            cursor: canSave ? 'pointer' : 'default',
            opacity: canSave ? 1 : 0.5,
          }}
        >
          {editing ? 'Save' : 'Add item'}
        </button>
        {editing && (
          <button
            onClick={handleDelete}
            style={{
              minHeight: '46px',
              padding: '0 16px',
              border: 'none',
              borderRadius: '12px',
              background: 'var(--surface)',
              color: 'var(--destructive)',
              fontSize: '15.5px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Delete
          </button>
        )}
      </div>
    </Sheet>
  )
}
