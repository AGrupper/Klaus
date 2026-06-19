/**
 * TaskDetailSheet.tsx — Bottom sheet (phone) / centered modal (desktop) for
 * creating and editing tasks.
 *
 * Phone: slides up from bottom (CSS transform translateY, 250ms ease-out),
 *        matching the Phase 26 DockChat collapse pattern. Drag handle at top.
 *        Dismisses by tapping the scrim.
 *
 * Desktop: centered modal, max-width 480px, #0A0A0A scrim opacity 0.7.
 *
 * CTA states (context-aware):
 *   - New task (task=null): "Add task" — accent 44px button
 *   - Edit task (task≠null): "Save changes" — accent 44px button
 *
 * Fields in order (UI-SPEC § Interaction Contracts):
 *   1. Title (single-line)
 *   2. Notes (multi-line, 3 rows)
 *   3. Due date (input[type=date])
 *   4. "Add time" toggle → input[type=time]
 *   5. Priority (None/Low/Medium/High select)
 *   6. List selector
 *   7. RecurrenceSelector
 *
 * Recurring task edit: if editing a recurring task, a 2-choice action sheet
 * appears before saving: "This occurrence only" / "This and following".
 *
 * Optimistic mutations: onMutate (cancel + snapshot + optimistic setQueryData),
 * onError (rollback + error toast), onSettled (invalidate).
 *
 * Security note (T-27-TI): title and notes rendered as input values (safe).
 */

import { useState, useEffect } from 'react'
import { GripHorizontal, ChevronDown } from 'lucide-react'
import { useCreateTask, useUpdateTask } from '../../hooks/useTasks'
import { useTaskLists } from '../../hooks/useTaskLists'
import { RecurrenceSelector } from './RecurrenceSelector'
import { useUndoStore } from '../../store/undoStore'
import { hardDeleteTask } from '../../api/tasks'
import type { Task, Priority, RecurrenceRule } from '../../api/tasks'
import {
  accent,
  border,
  destructive,
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

interface TaskDetailSheetProps {
  /** null → create mode; Task → edit mode */
  task: Task | null
  /** The list to create the task in (ignored in edit mode). */
  defaultListId?: string
  /** Called to close the sheet (after save or cancel). */
  onClose: () => void
  /** Whether the sheet is open. */
  open: boolean
}

// ---------------------------------------------------------------------------
// Error toast (lightweight inline)
// ---------------------------------------------------------------------------

function ErrorMessage({ message }: { message: string }) {
  if (!message) return null
  return (
    <div
      role="alert"
      style={{
        padding: '10px 14px',
        backgroundColor: `${destructive}22`,
        border: `1px solid ${destructive}`,
        borderRadius: '8px',
        color: destructive,
        fontSize: typography.label.fontSize,
        fontFamily,
      }}
    >
      {message}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recurring edit scope dialog (inline action sheet)
// ---------------------------------------------------------------------------

type RecurringScope = 'this_only' | 'this_and_following'

interface RecurringScopeSheetProps {
  onSelect: (scope: RecurringScope) => void
  onCancel: () => void
}

function RecurringScopeSheet({ onSelect, onCancel }: RecurringScopeSheetProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onCancel}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(10,10,10,0.7)',
          zIndex: 110,
        }}
        aria-hidden="true"
      />
      {/* Sheet */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          width: '100%',
          maxWidth: '480px',
          backgroundColor: secondary,
          borderTop: `1px solid ${border}`,
          borderRadius: '16px 16px 0 0',
          padding: '16px',
          zIndex: 120,
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
        role="dialog"
        aria-modal="true"
        aria-label="Edit recurring task"
      >
        {/* Heading */}
        <h3
          style={{
            margin: 0,
            fontSize: typography.body.fontSize,
            fontWeight: 600,
            fontFamily,
            color: textPrimary,
            textAlign: 'center',
            paddingBottom: '8px',
            borderBottom: `1px solid ${border}`,
          }}
        >
          Edit recurring task
        </h3>

        <button
          onClick={() => onSelect('this_only')}
          style={{
            width: '100%',
            minHeight: '44px',
            padding: '10px 16px',
            border: 'none',
            backgroundColor: 'transparent',
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontFamily,
            cursor: 'pointer',
            borderRadius: '8px',
            textAlign: 'left',
          }}
        >
          This occurrence only
        </button>

        <button
          onClick={() => onSelect('this_and_following')}
          style={{
            width: '100%',
            minHeight: '44px',
            padding: '10px 16px',
            border: 'none',
            backgroundColor: 'transparent',
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontFamily,
            cursor: 'pointer',
            borderRadius: '8px',
            textAlign: 'left',
          }}
        >
          This and following
        </button>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Field label helper
// ---------------------------------------------------------------------------

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label
      style={{
        display: 'block',
        fontSize: typography.label.fontSize,
        fontWeight: 600,
        fontFamily,
        color: textSecondary,
        marginBottom: '4px',
        textTransform: 'uppercase' as const,
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </label>
  )
}

// ---------------------------------------------------------------------------
// TaskDetailSheet
// ---------------------------------------------------------------------------

export function TaskDetailSheet({ task, defaultListId = 'inbox', onClose, open }: TaskDetailSheetProps) {
  const isCreate = task === null
  const { data: lists = [] } = useTaskLists()
  const createTask = useCreateTask(defaultListId)
  const updateTask = useUpdateTask(task?.list_id)

  // Form state
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [addTime, setAddTime] = useState(false)
  const [dueTime, setDueTime] = useState('')
  const [priority, setPriority] = useState<Priority>('none')
  const [listId, setListId] = useState(defaultListId)
  const [recurrence, setRecurrence] = useState<RecurrenceRule | null>(null)

  // UI state
  const [errorMsg, setErrorMsg] = useState('')
  const [showRecurringScope, setShowRecurringScope] = useState(false)
  const [listDropdownOpen, setListDropdownOpen] = useState(false)

  // Undo store (for delete from sheet)
  const undoShow = useUndoStore((s) => s.show)
  const undoActiveItem = useUndoStore((s) => s.activeItem)

  // Animation
  const [slideIn, setSlideIn] = useState(false)

  // Populate form when task changes
  useEffect(() => {
    if (task) {
      setTitle(task.title)
      setNotes(task.notes ?? '')
      setDueDate(task.due_date ?? '')
      setAddTime(!!task.due_time)
      setDueTime(task.due_time ?? '')
      setPriority(task.priority)
      setListId(task.list_id)
      setRecurrence(task.recurrence)
    } else {
      setTitle('')
      setNotes('')
      setDueDate('')
      setAddTime(false)
      setDueTime('')
      setPriority('none')
      setListId(defaultListId)
      setRecurrence(null)
    }
    setErrorMsg('')
  }, [task, defaultListId, open])

  // Slide-in animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  if (!open) return null

  // ---------------------------------------------------------------------------
  // Save handler
  // ---------------------------------------------------------------------------

  function handleSave(recurringScope?: RecurringScope) {
    setErrorMsg('')
    if (!title.trim()) {
      setErrorMsg("Title can't be empty.")
      return
    }

    if (isCreate) {
      createTask.mutate(
        {
          title: title.trim(),
          notes: notes.trim() || undefined,
          due_date: dueDate || null,
          due_time: addTime && dueTime ? dueTime : null,
          priority,
          list_id: listId,
          recurrence,
        },
        {
          onSuccess: () => { onClose() },
          onError: () => { setErrorMsg("Couldn't save task — try again.") },
        },
      )
    } else if (task) {
      const patch: Parameters<typeof updateTask.mutate>[0]['patch'] = {
        title: title.trim(),
        notes: notes.trim() || null,
        due_date: dueDate || null,
        due_time: addTime && dueTime ? dueTime : null,
        priority,
        list_id: listId,
        recurrence,
      }

      // Attach scope if recurring
      if (recurringScope) {
        ;(patch as Record<string, unknown>).scope = recurringScope
      }

      updateTask.mutate(
        { id: task.id, patch },
        {
          onSuccess: () => { onClose() },
          onError: () => { setErrorMsg("Couldn't update task — try again.") },
        },
      )
    }
  }

  function handleCtaTap() {
    // If editing a recurring task, show the scope dialog first
    if (!isCreate && task?.recurrence) {
      setShowRecurringScope(true)
      return
    }
    handleSave()
  }

  function handleRecurringScopeSelect(scope: RecurringScope) {
    setShowRecurringScope(false)
    handleSave(scope)
  }

  function handleDelete() {
    if (!task) return

    // Replace any existing undo item
    if (undoActiveItem && undoActiveItem.id !== task.id) {
      hardDeleteTask(undoActiveItem.id).catch(() => {})
    }

    undoShow({
      id: task.id,
      action: 'delete',
      listId: task.list_id,
      nextId: null,
    })
    onClose()
  }

  // ---------------------------------------------------------------------------
  // Layout helpers
  // ---------------------------------------------------------------------------

  const allLists = [{ id: 'inbox', name: 'Inbox' }, ...lists]
  const selectedListName = allLists.find((l) => l.id === listId)?.name ?? 'Inbox'

  const inputCss: React.CSSProperties = {
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
  }

  const selectCss: React.CSSProperties = {
    ...inputCss,
    cursor: 'pointer',
    appearance: 'none' as const,
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768

  return (
    <>
      {/* Scrim */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(10,10,10,0.7)',
          zIndex: 90,
        }}
        aria-hidden="true"
      />

      {/* Sheet / Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isCreate ? 'Add task' : 'Edit task'}
        style={{
          position: 'fixed',
          zIndex: 91,
          ...(isPhone
            ? {
                // Phone: bottom sheet
                left: 0,
                right: 0,
                bottom: 0,
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
                borderRadius: '16px',
              }),
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          maxHeight: '90dvh',
          overflowY: 'auto',
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

        {/* Form body */}
        <div
          style={{
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
            flex: 1,
          }}
        >
          {errorMsg && <ErrorMessage message={errorMsg} />}

          {/* Title */}
          <div>
            <FieldLabel>Title</FieldLabel>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Task title"
              autoFocus
              style={inputCss}
              aria-label="Task title"
            />
          </div>

          {/* Notes */}
          <div>
            <FieldLabel>Notes</FieldLabel>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Notes"
              rows={3}
              style={{
                ...inputCss,
                resize: 'none' as const,
                fontFamily,
              }}
              aria-label="Task notes"
            />
          </div>

          {/* Due date */}
          <div>
            <FieldLabel>Due date</FieldLabel>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              style={inputCss}
              aria-label="Due date"
            />
          </div>

          {/* Add time toggle */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <input
              type="checkbox"
              id="add-time-toggle"
              checked={addTime}
              onChange={(e) => {
                setAddTime(e.target.checked)
                if (!e.target.checked) setDueTime('')
              }}
              style={{ width: '18px', height: '18px', accentColor: accent, cursor: 'pointer' }}
              aria-label="Add time"
            />
            <label
              htmlFor="add-time-toggle"
              style={{
                fontSize: typography.body.fontSize,
                fontFamily,
                color: textPrimary,
                cursor: 'pointer',
              }}
            >
              Add time
            </label>
            {addTime && (
              <input
                type="time"
                value={dueTime}
                onChange={(e) => setDueTime(e.target.value)}
                style={{ ...inputCss, width: '130px' }}
                aria-label="Due time"
              />
            )}
          </div>

          {/* Priority */}
          <div>
            <FieldLabel>Priority</FieldLabel>
            <div style={{ position: 'relative' }}>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as Priority)}
                style={selectCss}
                aria-label="Priority"
              >
                <option value="none">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <span
                style={{
                  position: 'absolute',
                  right: '12px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  pointerEvents: 'none',
                  color: textSecondary,
                  fontSize: '12px',
                }}
              >
                ▾
              </span>
            </div>
          </div>

          {/* List */}
          <div>
            <FieldLabel>List</FieldLabel>
            <div style={{ position: 'relative' }}>
              <button
                onClick={() => setListDropdownOpen((p) => !p)}
                style={{
                  ...selectCss,
                  textAlign: 'left' as const,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  border: `1px solid ${border}`,
                }}
                aria-label="Select list"
                aria-expanded={listDropdownOpen}
              >
                <span>{selectedListName}</span>
                <ChevronDown size={14} color={textSecondary} aria-hidden="true" />
              </button>

              {/* Dropdown */}
              {listDropdownOpen && (
                <>
                  <div
                    onClick={() => setListDropdownOpen(false)}
                    style={{ position: 'fixed', inset: 0, zIndex: 49 }}
                    aria-hidden="true"
                  />
                  <div
                    style={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      right: 0,
                      marginTop: '4px',
                      backgroundColor: secondary,
                      border: `1px solid ${border}`,
                      borderRadius: '8px',
                      overflow: 'hidden',
                      zIndex: 50,
                      boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                    }}
                  >
                    {allLists.map((l) => (
                      <button
                        key={l.id}
                        onClick={() => { setListId(l.id); setListDropdownOpen(false) }}
                        style={{
                          display: 'block',
                          width: '100%',
                          padding: '10px 14px',
                          border: 'none',
                          backgroundColor: l.id === listId ? `${accent}22` : 'transparent',
                          color: l.id === listId ? accent : textPrimary,
                          fontSize: typography.label.fontSize,
                          fontFamily,
                          cursor: 'pointer',
                          textAlign: 'left' as const,
                          borderLeft: l.id === listId ? `3px solid ${accent}` : '3px solid transparent',
                        }}
                      >
                        {l.name}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Recurrence */}
          <div>
            <FieldLabel>Repeat</FieldLabel>
            <RecurrenceSelector value={recurrence} onChange={setRecurrence} />
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: `1px solid ${border}`,
            display: 'flex',
            flexDirection: isPhone ? 'column' : 'row',
            alignItems: isPhone ? 'stretch' : 'center',
            gap: '10px',
            flexShrink: 0,
          }}
        >
          {/* Desktop layout: delete left, spacer, cancel + cta right */}
          {!isCreate && (
            <button
              onClick={handleDelete}
              style={{
                height: '44px',
                padding: '0 16px',
                border: 'none',
                backgroundColor: 'transparent',
                color: destructive,
                fontSize: typography.body.fontSize,
                fontFamily,
                cursor: 'pointer',
                ...(isPhone ? {} : { marginRight: 'auto' }),
              }}
            >
              Delete task
            </button>
          )}

          {/* Cancel */}
          <button
            onClick={onClose}
            style={{
              height: '44px',
              padding: '0 16px',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              fontSize: typography.body.fontSize,
              fontFamily,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>

          {/* CTA */}
          <button
            onClick={handleCtaTap}
            disabled={createTask.isPending || updateTask.isPending}
            style={{
              height: '44px',
              padding: '0 24px',
              border: 'none',
              borderRadius: '10px',
              backgroundColor: accent,
              color: '#FFFFFF',
              fontSize: typography.body.fontSize,
              fontWeight: 600,
              fontFamily,
              cursor: 'pointer',
              opacity: (createTask.isPending || updateTask.isPending) ? 0.7 : 1,
              ...(isPhone ? { width: '100%' } : {}),
            }}
          >
            {isCreate ? 'Add task' : 'Save changes'}
          </button>
        </div>
      </div>

      {/* Recurring scope dialog */}
      {showRecurringScope && (
        <RecurringScopeSheet
          onSelect={handleRecurringScopeSelect}
          onCancel={() => setShowRecurringScope(false)}
        />
      )}
    </>
  )
}
