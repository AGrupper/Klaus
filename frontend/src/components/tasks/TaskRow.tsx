/**
 * TaskRow.tsx — Single task row with completion micro-animation.
 *
 * Completion micro-animation (UI-SPEC § Interaction Contracts):
 *   1. Checkbox tap: circle fills success green (150ms ease-out)
 *   2. Checkmark SVG draws in (150ms stroke-dashoffset)
 *   3. Row collapses to max-height: 0 (200ms, overflow hidden)
 *   Total: ~500ms
 *
 * Soft-mark → 4s → hard-delete flow:
 *   1. Tap checkbox: completeTask(id) fires; undoStore.show({...})
 *   2. 4s browser setTimeout (in UndoToast) → hardDeleteTask(id)
 *   3. Undo: undoTask(id) + invalidate query
 *
 * Delete flow (swipe or ⋯ menu on phone / ⋯ menu on desktop):
 *   - Same 4s soft-mark → hard-delete (no confirmation modal — D-14)
 *   - Toast copy: "Task deleted."
 *
 * Security note (T-27-TI): title and notes are rendered as plain text React
 * children — never via raw HTML injection.
 */

import { useState, useRef } from 'react'
import {
  Circle,
  CheckCircle2,
  Flag,
  CalendarDays,
  RotateCcw,
  AlertCircle,
  MoreHorizontal,
  Trash2,
} from 'lucide-react'
import { useCompleteTask, useSoftDeleteTask } from '../../hooks/useTasks'
import { useUndoStore } from '../../store/undoStore'
import { hardDeleteTask } from '../../api/tasks'
import type { Task, Priority } from '../../api/tasks'
import {
  border,
  destructive,
  dominant,
  secondary,
  success,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TaskRowProps {
  task: Task
  listId: string
  onOpenTask: () => void
}

// ---------------------------------------------------------------------------
// Priority chip
// ---------------------------------------------------------------------------

const PRIORITY_STYLE: Record<Priority, { label: string; color: string; bg: string | null }> = {
  high:   { label: 'High',   color: '#F87171', bg: '#2A1A1A' },
  medium: { label: 'Medium', color: '#FBBF24', bg: '#2A2010' },
  low:    { label: 'Low',    color: textSecondary, bg: null },
  none:   { label: '',       color: '',         bg: null },
}

function PriorityChip({ priority }: { priority: Priority }) {
  const style = PRIORITY_STYLE[priority]
  if (priority === 'none') return null
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '3px',
        padding: style.bg ? '2px 6px' : '0',
        borderRadius: '4px',
        backgroundColor: style.bg ?? 'transparent',
        color: style.color,
        fontSize: typography.label.fontSize,
        fontFamily,
        flexShrink: 0,
      }}
    >
      <Flag size={10} strokeWidth={2} aria-hidden="true" />
      {style.label}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Due date chip
// ---------------------------------------------------------------------------

function DueDateChip({ dueDate, dueTime }: { dueDate: string; dueTime: string | null }) {
  const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })
  const isOverdue = dueDate < todayStr

  // Format the date: "D Mon" e.g. "18 Jun"
  const [, month, day] = dueDate.split('-').map(Number)
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const formatted = `${day} ${monthNames[month - 1]}`

  // Calculate overdue days
  let overdueDays = 0
  if (isOverdue) {
    const today = new Date(todayStr + 'T00:00:00')
    const due = new Date(dueDate + 'T00:00:00')
    overdueDays = Math.round((today.getTime() - due.getTime()) / (1000 * 60 * 60 * 24))
  }

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '3px',
        color: isOverdue ? destructive : textSecondary,
        fontSize: typography.label.fontSize,
        fontFamily,
        flexShrink: 0,
      }}
    >
      {isOverdue ? (
        <>
          <AlertCircle size={11} strokeWidth={2} aria-hidden="true" />
          {overdueDays}d overdue
        </>
      ) : (
        <>
          <CalendarDays size={11} strokeWidth={2} aria-hidden="true" />
          {formatted}
          {dueTime && <span style={{ marginLeft: '2px' }}>{dueTime}</span>}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TaskRow
// ---------------------------------------------------------------------------

export function TaskRow({ task, listId, onOpenTask }: TaskRowProps) {
  const completeTaskMutation = useCompleteTask(listId)
  const softDeleteMutation = useSoftDeleteTask(listId)
  const undoShow = useUndoStore((s) => s.show)
  const undoActiveItem = useUndoStore((s) => s.activeItem)

  // Animation state
  const [animating, setAnimating] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [showCheckmark, setShowCheckmark] = useState(false)

  // Kebab (⋯) menu state — shown on all breakpoints (phone + desktop)
  const [kebabOpen, setKebabOpen] = useState(false)
  const kebabRef = useRef<HTMLDivElement>(null)

  // Swipe state (phone)
  const [swipeX, setSwipeX] = useState(0)
  const touchStartX = useRef<number | null>(null)

  // ---------------------------------------------------------------------------
  // Completion flow
  // ---------------------------------------------------------------------------

  function handleComplete() {
    if (animating) return

    // If there's an existing undo item (different task), fire its hard-delete now
    if (undoActiveItem && undoActiveItem.id !== task.id) {
      hardDeleteTask(undoActiveItem.id).catch(() => {})
    }

    setAnimating(true)

    // Phase 1: circle fill (0–150ms)
    // Phase 2: checkmark draw (150–300ms)
    setTimeout(() => {
      setShowCheckmark(true)
    }, 150)

    // Phase 3: row collapse (300–500ms)
    setTimeout(() => {
      setCollapsed(true)
    }, 300)

    // After collapse: fire the API + undoStore
    setTimeout(() => {
      const completedOn = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })
      completeTaskMutation.mutate(
        { id: task.id, completedOn },
        {
          onSuccess: (data) => {
            undoShow({
              id: task.id,
              action: 'complete',
              listId,
              nextId: data.next_id,
            })
          },
          onError: () => {
            // Rollback animation
            setAnimating(false)
            setCollapsed(false)
            setShowCheckmark(false)
          },
        },
      )
    }, 500)
  }

  // ---------------------------------------------------------------------------
  // Delete flow (kebab or swipe)
  // ---------------------------------------------------------------------------

  function handleDelete() {
    if (animating) return

    // If there's an existing undo item (different task), fire its hard-delete now
    if (undoActiveItem && undoActiveItem.id !== task.id) {
      hardDeleteTask(undoActiveItem.id).catch(() => {})
    }

    setAnimating(true)
    setCollapsed(true)

    // After the collapse animation, soft-mark the task 'completing' on the
    // server (so the deferred hard-delete is allowed — without this the row
    // reappeared because hard-delete 409'd on an active task), then open the
    // undo window. The 4s timer in UndoToast fires hardDeleteTask; Undo reverts.
    setTimeout(() => {
      softDeleteMutation.mutate(
        { id: task.id },
        {
          onSuccess: () => {
            undoShow({
              id: task.id,
              action: 'delete',
              listId,
              nextId: null,
            })
          },
          onError: () => {
            // Rollback the collapse animation if the soft-delete failed
            setAnimating(false)
            setCollapsed(false)
          },
        },
      )
    }, 200)
  }

  // ---------------------------------------------------------------------------
  // Touch/swipe (phone reveal delete)
  // ---------------------------------------------------------------------------

  function handleTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX
  }

  function handleTouchMove(e: React.TouchEvent) {
    if (touchStartX.current === null) return
    const dx = e.touches[0].clientX - touchStartX.current
    if (dx < 0) {
      setSwipeX(Math.max(dx, -72)) // max reveal 72px
    }
  }

  function handleTouchEnd() {
    touchStartX.current = null
    if (swipeX < -36) {
      // Swiped past threshold — reveal delete fully
      setSwipeX(-72)
    } else {
      setSwipeX(0)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const rowStyle: React.CSSProperties = {
    position: 'relative' as const,
    // While the kebab menu is open: (1) overflow visible so the dropdown isn't
    // clipped by this row, and (2) lift the whole row above sibling rows — each
    // row's inner div has a `transform` (its own stacking context), so without
    // this the next row in the DOM paints over the open menu.
    zIndex: kebabOpen ? 30 : undefined,
    maxHeight: collapsed ? '0' : '200px',
    overflow: kebabOpen ? 'visible' : 'hidden',
    transition: collapsed ? 'max-height 0.2s ease-out' : 'none',
    backgroundColor: dominant,
    borderBottom: `1px solid ${border}`,
  }

  const innerStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    minHeight: '52px',
    padding: '8px 0 8px 0',
    transform: `translateX(${swipeX}px)`,
    transition: swipeX === 0 ? 'transform 0.2s ease' : 'none',
    backgroundColor: dominant,
    position: 'relative' as const,
    zIndex: 1,
  }

  return (
    <div style={rowStyle}>
      {/* Swipe-reveal delete button (phone) */}
      {swipeX <= -36 && (
        <button
          onClick={handleDelete}
          style={{
            position: 'absolute' as const,
            right: 0,
            top: 0,
            bottom: 0,
            width: '72px',
            backgroundColor: destructive,
            border: 'none',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            zIndex: 0,
          }}
          aria-label="Delete task"
        >
          <Trash2 size={18} strokeWidth={2} />
        </button>
      )}

      <div
        style={innerStyle}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Checkbox — 44px tap target */}
        <button
          onClick={handleComplete}
          style={{
            width: '44px',
            height: '44px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            border: 'none',
            backgroundColor: 'transparent',
            cursor: 'pointer',
            color: animating ? success : textSecondary,
            transition: 'color 0.15s ease-out',
            padding: 0,
          }}
          aria-label={`Complete task: ${task.title}`}
          disabled={animating}
        >
          {animating ? (
            <CheckCircle2
              size={20}
              strokeWidth={2}
              style={{
                color: success,
                // Checkmark animation via opacity (stroke-dashoffset handled via SVG)
                opacity: showCheckmark ? 1 : 0,
                transition: 'opacity 0.15s ease-out',
              }}
              aria-hidden="true"
            />
          ) : (
            <Circle size={20} strokeWidth={1.5} aria-hidden="true" />
          )}
        </button>

        {/* Task body — tap to edit */}
        <button
          onClick={onOpenTask}
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column' as const,
            alignItems: 'flex-start',
            gap: '4px',
            border: 'none',
            backgroundColor: 'transparent',
            cursor: 'pointer',
            padding: '0 8px 0 0',
            minWidth: 0,
          }}
          aria-label={`Edit task: ${task.title}`}
        >
          {/* Title */}
          <span
            style={{
              fontSize: typography.body.fontSize,
              fontFamily,
              color: textPrimary,
              textAlign: 'left' as const,
              width: '100%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap' as const,
            }}
          >
            {task.title}
          </span>

          {/* Meta row: priority chip + due chip + recurrence */}
          {(task.priority !== 'none' || task.due_date || task.recurrence) && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                flexWrap: 'wrap' as const,
              }}
            >
              {task.priority !== 'none' && <PriorityChip priority={task.priority} />}
              {task.due_date && (
                <DueDateChip dueDate={task.due_date} dueTime={task.due_time} />
              )}
              {task.recurrence && (
                <RotateCcw
                  size={11}
                  strokeWidth={2}
                  aria-label="Recurring"
                  style={{ color: textSecondary, flexShrink: 0 }}
                />
              )}
              {/* List name shown when not in its own list context */}
              {task.list_id !== listId && (
                <span
                  style={{
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    color: textSecondary,
                  }}
                >
                  {task.list_id === 'inbox' ? 'Inbox' : task.list_id}
                </span>
              )}
            </div>
          )}
        </button>

        {/* Task options (⋯) menu — shown on phone and desktop. No inline
            `display` here, so nothing fights a Tailwind class; it renders on
            every breakpoint. (Phone also keeps swipe-to-delete, above.) */}
        <div
          ref={kebabRef}
          style={{ position: 'relative' as const, flexShrink: 0, marginRight: '8px' }}
        >
          <button
            onClick={() => setKebabOpen((p) => !p)}
            aria-label="Task options"
            style={{
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              cursor: 'pointer',
              borderRadius: '6px',
              transition: 'color 0.15s',
            }}
          >
            <MoreHorizontal size={16} strokeWidth={2} aria-hidden="true" />
          </button>

          {/* Kebab dropdown */}
          {kebabOpen && (
            <>
              <div
                onClick={() => setKebabOpen(false)}
                style={{ position: 'fixed' as const, inset: 0, zIndex: 49 }}
                aria-hidden="true"
              />
              <div
                style={{
                  position: 'absolute' as const,
                  right: 0,
                  top: '100%',
                  marginTop: '4px',
                  backgroundColor: secondary,
                  border: `1px solid ${border}`,
                  borderRadius: '8px',
                  overflow: 'hidden',
                  zIndex: 50,
                  minWidth: '120px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                }}
              >
                <button
                  onClick={() => { setKebabOpen(false); onOpenTask() }}
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '10px 14px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    color: textPrimary,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    textAlign: 'left' as const,
                  }}
                >
                  Edit
                </button>
                <button
                  onClick={() => { setKebabOpen(false); handleDelete() }}
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '10px 14px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    color: destructive,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    cursor: 'pointer',
                    textAlign: 'left' as const,
                  }}
                >
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
