/**
 * RoutineEditSheet.tsx — create or edit a routine group (name, emoji, delete).
 *
 * Deleting detaches member habits to Unassigned (server-side) — history is
 * never touched, so no undo window is needed here.
 */
import { useEffect, useState } from 'react'
import type { Routine } from '../../api/routines'
import { useCreateRoutine, useDeleteRoutine, useEditRoutine } from '../../hooks/useRoutines'
import { Sheet } from '../shared/Sheet'

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

interface RoutineEditSheetProps {
  /** null = create mode */
  routine: Routine | null
  open: boolean
  onClose: () => void
}

export function RoutineEditSheet({ routine, open, onClose }: RoutineEditSheetProps) {
  const [name, setName] = useState('')
  const [emoji, setEmoji] = useState('')
  const createMutation = useCreateRoutine()
  const editMutation = useEditRoutine()
  const deleteMutation = useDeleteRoutine()

  useEffect(() => {
    if (open) {
      setName(routine?.name ?? '')
      setEmoji(routine?.emoji ?? '')
    }
  }, [open, routine])

  const editing = routine !== null && routine.id !== null
  const canSave = name.trim().length > 0

  function handleSave() {
    if (!canSave) return
    const input = { name: name.trim(), emoji: emoji.trim() || null }
    if (editing && routine?.id) {
      editMutation.mutate({ id: routine.id, input })
    } else {
      createMutation.mutate(input)
    }
    onClose()
  }

  function handleDelete() {
    if (editing && routine?.id) {
      deleteMutation.mutate(routine.id)
      onClose()
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={editing ? 'Edit routine' : 'New routine'}>
      <label style={labelStyle} htmlFor="routine-name">Name</label>
      <input
        id="routine-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Morning routine"
        maxLength={200}
        style={inputStyle}
      />

      <label style={labelStyle} htmlFor="routine-emoji">Emoji (optional)</label>
      <input
        id="routine-emoji"
        value={emoji}
        onChange={(e) => setEmoji(e.target.value)}
        placeholder="☀️"
        maxLength={4}
        style={{ ...inputStyle, width: '90px' }}
      />

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
          {editing ? 'Save' : 'Create routine'}
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
      {editing && (
        <p style={{ fontSize: '12.5px', color: 'var(--muted)', lineHeight: 1.5 }}>
          Deleting a routine keeps its habits and their history — they move to Unassigned.
        </p>
      )}
    </Sheet>
  )
}
