/**
 * RoutineEditSheet.tsx — create or edit a routine group.
 *
 * Fields: name · emoji · colour · time of day. From Amit's 2026-08-17 UAT:
 *  - colour is per-routine (the ring, the flame badge and its Today dot),
 *  - "time of day" is the anchor that places it in the Today timeline, so a
 *    morning routine sits at the top of the day rather than the bottom,
 *  - deleting now asks what to do with the items instead of silently
 *    dumping them into "Unassigned".
 */
import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import type { Routine } from '../../api/routines'
import { useCreateRoutine, useDeleteRoutine, useEditRoutine } from '../../hooks/useRoutines'
import { useUndoStore } from '../../store/undoStore'
import { CALENDAR_COLORS, normalizeHex } from '../../tokens'
import { tapFeedback } from '../../utils/haptics'
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
  const [color, setColor] = useState<string>(CALENDAR_COLORS[0].hex)
  const [anchorTime, setAnchorTime] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const createMutation = useCreateRoutine()
  const editMutation = useEditRoutine()
  const deleteMutation = useDeleteRoutine()
  const undoShow = useUndoStore((s) => s.show)

  useEffect(() => {
    if (!open) return
    setName(routine?.name ?? '')
    setEmoji(routine?.emoji ?? '')
    setColor(routine?.color ?? CALENDAR_COLORS[0].hex)
    setAnchorTime(routine?.anchor_time ?? '')
    setConfirmingDelete(false)
  }, [open, routine])

  const editing = routine !== null && routine.id !== null
  const canSave = name.trim().length > 0
  const itemCount = routine?.habits.length ?? 0

  function handleSave() {
    if (!canSave) return
    const input = {
      name: name.trim(),
      emoji: emoji.trim() || null,
      color: normalizeHex(color) ?? null,
      anchor_time: anchorTime || null,
    }
    if (editing && routine?.id) {
      editMutation.mutate({ id: routine.id, input })
    } else {
      createMutation.mutate(input)
    }
    onClose()
  }

  function handleDelete(withItems: boolean) {
    if (!editing || !routine?.id) return
    deleteMutation.mutate(
      { id: routine.id, withItems },
      {
        onSuccess: (result) => {
          // Deleting the items opens the same 4s undo window as any habit
          // delete, so a mis-tap is recoverable.
          const [firstRemoved] = result?.removed_habit_ids ?? []
          if (firstRemoved) {
            undoShow({
              id: firstRemoved,
              action: 'delete',
              listId: 'habits',
              nextId: null,
              resourceType: 'habit',
            })
          }
        },
      },
    )
    onClose()
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

      <div style={{ display: 'flex', gap: '14px' }}>
        <div>
          <label style={labelStyle} htmlFor="routine-emoji">Emoji</label>
          <input
            id="routine-emoji"
            value={emoji}
            onChange={(e) => setEmoji(e.target.value)}
            placeholder="☀️"
            maxLength={4}
            style={{ ...inputStyle, width: '84px' }}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle} htmlFor="routine-time">Time of day</label>
          <input
            id="routine-time"
            type="time"
            value={anchorTime}
            onChange={(e) => setAnchorTime(e.target.value)}
            style={inputStyle}
          />
        </div>
      </div>
      <p style={{ fontSize: '12px', color: 'var(--muted)', margin: '6px 2px 0', lineHeight: 1.45 }}>
        Sets where the routine appears in Today. Leave empty to keep it at the
        end of the day.
      </p>

      <span style={labelStyle}>Colour</span>
      <div
        role="radiogroup"
        aria-label="Routine colour"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}
      >
        {CALENDAR_COLORS.map(({ name, hex }) => {
          const selected = color.toUpperCase() === hex.toUpperCase()
          return (
            <button
              key={hex}
              role="radio"
              aria-checked={selected}
              aria-label={name}
              title={name}
              className="press"
              onClick={() => {
                tapFeedback()
                setColor(hex)
              }}
              style={{
                aspectRatio: '1',
                width: '100%',
                borderRadius: '50%',
                border: 'none',
                background: hex,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: selected
                  ? '0 0 0 3px var(--ground), 0 0 0 5px var(--ink)'
                  : 'none',
                transition: 'box-shadow 0.18s var(--ease)',
              }}
            >
              {selected && <Check size={15} color="#FFFFFF" strokeWidth={3.5} aria-hidden="true" />}
            </button>
          )
        })}
      </div>

      <div style={{ display: 'flex', gap: '10px', margin: '22px 0 6px' }}>
        <button
          onClick={handleSave}
          disabled={!canSave}
          className="press"
          style={{
            flex: 1,
            minHeight: '48px',
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
        {editing && !confirmingDelete && (
          <button
            onClick={() => setConfirmingDelete(true)}
            className="press"
            style={{
              minHeight: '48px',
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

      {editing && confirmingDelete && (
        <div
          style={{
            background: 'var(--surface)',
            borderRadius: 'var(--r)',
            padding: '14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
            marginTop: '4px',
            maxWidth: '100%',
            minWidth: 0,
          }}
        >
          <span style={{ fontSize: '14px', color: 'var(--ink)', lineHeight: 1.5, overflowWrap: 'anywhere' }}>
            Delete “{routine?.name}”
            {itemCount > 0 ? ` and its ${itemCount} item${itemCount === 1 ? '' : 's'}?` : '?'}
          </span>
          <button
            onClick={() => handleDelete(true)}
            className="press"
            style={{
              minHeight: '46px',
              padding: '10px 12px',
              border: 'none',
              borderRadius: '12px',
              background: 'var(--destructive)',
              color: '#FFFFFF',
              fontSize: '15px',
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'normal',
              lineHeight: 1.3,
            }}
          >
            {itemCount > 0 ? 'Delete routine and items' : 'Delete routine'}
          </button>
          {itemCount > 0 && (
            <button
              onClick={() => handleDelete(false)}
              className="press"
              style={{
                minHeight: '46px',
                padding: '10px 12px',
                border: 'none',
                borderRadius: '12px',
                background: 'var(--ground)',
                color: 'var(--ink)',
                fontSize: '15px',
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'normal',
                lineHeight: 1.3,
              }}
            >
              Keep the items, delete only the routine
            </button>
          )}
          <button
            onClick={() => setConfirmingDelete(false)}
            style={{
              minHeight: '40px',
              border: 'none',
              background: 'none',
              color: 'var(--muted)',
              fontSize: '14px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      )}
    </Sheet>
  )
}
