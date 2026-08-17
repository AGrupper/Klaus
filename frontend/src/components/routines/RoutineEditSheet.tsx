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
import { useEffect, useRef, useState } from 'react'
import type { Routine } from '../../api/routines'
import { useCreateRoutine, useDeleteRoutine, useEditRoutine } from '../../hooks/useRoutines'
import { useUndoStore } from '../../store/undoStore'
import { normalizeHex } from '../../tokens'
import { Sheet } from '../shared/Sheet'

const COLOR_PRESETS = ['#B0762A', '#4C4C8F', '#B02A2A', '#20563A', '#1F4E63', '#8F2D3C']

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
  const [color, setColor] = useState<string>(COLOR_PRESETS[0])
  const [anchorTime, setAnchorTime] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const colorPicker = useRef<HTMLInputElement>(null)

  const createMutation = useCreateRoutine()
  const editMutation = useEditRoutine()
  const deleteMutation = useDeleteRoutine()
  const undoShow = useUndoStore((s) => s.show)

  useEffect(() => {
    if (!open) return
    setName(routine?.name ?? '')
    setEmoji(routine?.emoji ?? '')
    setColor(routine?.color ?? COLOR_PRESETS[0])
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
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {COLOR_PRESETS.map((preset) => (
          <button
            key={preset}
            onClick={() => setColor(preset)}
            aria-label={preset}
            aria-pressed={color.toUpperCase() === preset.toUpperCase()}
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '50%',
              border: color.toUpperCase() === preset.toUpperCase()
                ? '3px solid var(--ink)'
                : '3px solid transparent',
              background: preset,
              cursor: 'pointer',
              padding: 0,
            }}
          />
        ))}
        <button
          onClick={() => colorPicker.current?.click()}
          aria-label="Custom colour"
          style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            position: 'relative',
            border: COLOR_PRESETS.some((p) => p.toUpperCase() === color.toUpperCase())
              ? '3px solid transparent'
              : '3px solid var(--ink)',
            background: 'conic-gradient(#E8453C, #E8A23D, #3FA55B, #2E7CF6, #7C5CD6, #E8453C)',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <input
            ref={colorPicker}
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value.toUpperCase())}
            tabIndex={-1}
            aria-hidden="true"
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              opacity: 0, border: 'none', padding: 0, cursor: 'pointer',
            }}
          />
        </button>
      </div>

      <div style={{ display: 'flex', gap: '10px', margin: '22px 0 6px' }}>
        <button
          onClick={handleSave}
          disabled={!canSave}
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
          }}
        >
          <span style={{ fontSize: '14px', color: 'var(--ink)', lineHeight: 1.5 }}>
            Delete “{routine?.name}”
            {itemCount > 0 ? ` and its ${itemCount} item${itemCount === 1 ? '' : 's'}?` : '?'}
          </span>
          <button
            onClick={() => handleDelete(true)}
            style={{
              minHeight: '46px',
              border: 'none',
              borderRadius: '12px',
              background: 'var(--destructive)',
              color: '#FFFFFF',
              fontSize: '15px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {itemCount > 0 ? 'Delete routine and items' : 'Delete routine'}
          </button>
          {itemCount > 0 && (
            <button
              onClick={() => handleDelete(false)}
              style={{
                minHeight: '46px',
                border: 'none',
                borderRadius: '12px',
                background: 'var(--ground)',
                color: 'var(--ink)',
                fontSize: '15px',
                fontWeight: 600,
                cursor: 'pointer',
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
