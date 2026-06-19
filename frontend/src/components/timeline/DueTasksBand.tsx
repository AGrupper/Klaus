/**
 * DueTasksBand.tsx — Pinned "Due today" band on the Today timeline.
 *
 * UI-SPEC (§ Today Timeline — Due Tasks Band, D-11):
 *   - Rendered after all-day events, before timed events in TimelineDay.tsx
 *   - Only shown when due_today + overdue > 0 (no empty placeholder)
 *   - Section label "Due today" (13px, textSecondary) with accent left-border stripe
 *     (4px wide, 32px tall, #6366F1)
 *   - Each task row: checkbox (44px tap target) + title + overdue chip ("Nd overdue"
 *     in destructive red) when the task is overdue
 *   - Tapping a checkbox: same completion micro-animation + undo flow as Tasks page
 *   - Tapping a title row: navigates to /tasks
 *
 * Data strategy:
 *   - useTaskSummary() for the guard (due_today + overdue > 0) — shared with GlanceRail,
 *     react-query deduplicates the fetch via TASK_SUMMARY_QUERY_KEY
 *   - useTasks() (all tasks, no list filter) to get actual task rows; filtered client-side
 *     for tasks whose due_date matches today (due) or is before today (overdue)
 *
 * Security (T-27-TI): task titles rendered as plain React text children — never via
 * raw HTML injection.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Circle, CheckCircle2 } from 'lucide-react'
import { useTaskSummary } from '../../hooks/useTaskSummary'
import { useTasks, useCompleteTask } from '../../hooks/useTasks'
import { useUndoStore } from '../../store/undoStore'
import type { Task } from '../../api/tasks'
import {
  accent,
  destructive,
  success,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Get today's date as YYYY-MM-DD in the browser's local timezone.
 * We use the system locale since the band is displayed in the user's local context.
 */
function getTodayISO(): string {
  return new Date().toLocaleDateString('en-CA') // yields YYYY-MM-DD
}

/**
 * Compute how many days overdue a task is (positive = overdue).
 * Returns 0 if the task is due today or in the future.
 */
function daysOverdue(dueDate: string, todayISO: string): number {
  const due = new Date(dueDate + 'T12:00:00Z').getTime()
  const today = new Date(todayISO + 'T12:00:00Z').getTime()
  const msPerDay = 24 * 60 * 60 * 1000
  return Math.max(0, Math.floor((today - due) / msPerDay))
}

// ---------------------------------------------------------------------------
// BandTaskRow — a single task row inside the band
// ---------------------------------------------------------------------------

interface BandTaskRowProps {
  task: Task
  dueOverdueDays: number  // 0 = due today, >0 = overdue by N days
}

function BandTaskRow({ task, dueOverdueDays }: BandTaskRowProps) {
  const navigate = useNavigate()
  const completeTaskMutation = useCompleteTask(task.list_id)
  const showUndo = useUndoStore((s) => s.show)

  // Completion animation state (mirrors TaskRow.tsx)
  const [completing, setCompleting] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  function handleComplete(e: React.MouseEvent) {
    e.stopPropagation()
    if (completing || collapsed) return
    setCompleting(true)

    const completedOn = new Date().toLocaleDateString('en-CA')

    // Step 1 + 2: circle fills (150ms) + checkmark draws (150ms)
    setTimeout(() => {
      // Step 3: collapse row (200ms)
      setCollapsed(true)
      setTimeout(() => {
        // Fire the actual complete mutation
        completeTaskMutation.mutate(
          { id: task.id, completedOn },
          {
            onSuccess: (data) => {
              showUndo({
                id: task.id,
                action: 'complete',
                listId: task.list_id,
                nextId: data.next_id,
              })
            },
          },
        )
      }, 200)
    }, 300) // 150ms fill + 150ms checkmark
  }

  function handleTitleClick() {
    navigate('/tasks')
  }

  const isOverdue = dueOverdueDays > 0

  return (
    <div
      style={{
        maxHeight: collapsed ? '0' : '52px',
        overflow: 'hidden',
        transition: collapsed ? 'max-height 0.2s ease-out' : undefined,
        opacity: collapsed ? 0 : 1,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          minHeight: '44px',
          gap: '8px',
        }}
      >
        {/* Checkbox — 44px tap target */}
        <button
          onClick={handleComplete}
          aria-label={`Complete task: ${task.title}`}
          style={{
            width: '44px',
            height: '44px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: 'none',
            backgroundColor: 'transparent',
            cursor: 'pointer',
            flexShrink: 0,
            color: completing ? success : textSecondary,
            transition: 'color 0.15s ease-out',
          }}
        >
          {completing ? (
            <CheckCircle2 size={20} strokeWidth={2} aria-hidden="true" />
          ) : (
            <Circle size={20} strokeWidth={1.5} aria-hidden="true" />
          )}
        </button>

        {/* Title — taps navigate to /tasks */}
        <button
          onClick={handleTitleClick}
          style={{
            flex: 1,
            border: 'none',
            backgroundColor: 'transparent',
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontFamily,
            cursor: 'pointer',
            textAlign: 'left',
            padding: '0',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {task.title}
        </button>

        {/* Overdue chip — only when task is past-due */}
        {isOverdue && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              height: '24px',
              padding: '0 8px',
              backgroundColor: `${destructive}18`,
              border: `1px solid ${destructive}40`,
              borderRadius: '12px',
              color: destructive,
              fontSize: typography.label.fontSize,
              fontFamily,
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            {dueOverdueDays}d overdue
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// DueTasksBand
// ---------------------------------------------------------------------------

export function DueTasksBand() {
  // Guard: use useTaskSummary to decide whether to render at all.
  // React-query deduplicates this fetch with GlanceRail's useTaskSummary call.
  const { data: summary } = useTaskSummary()

  // Always call useTasks — hooks must not be conditional
  const { data: allTasks = [] } = useTasks(undefined)

  const todayISO = getTodayISO()

  // Filter to due-today and overdue tasks (active status only, due_date set and ≤ today)
  const dueTasks: Array<{ task: Task; overdueDays: number }> = allTasks
    .filter((t) => t.status === 'active' && t.due_date !== null && t.due_date <= todayISO)
    .map((t) => ({
      task: t,
      overdueDays: daysOverdue(t.due_date!, todayISO),
    }))
    .sort((a, b) => {
      // Show overdue tasks first (higher overdueDays first), then due today
      if (b.overdueDays !== a.overdueDays) return b.overdueDays - a.overdueDays
      return a.task.title.localeCompare(b.task.title)
    })

  // Guard: do not render if summary says 0 or if we have no filtered tasks
  const totalCount = (summary?.due_today ?? 0) + (summary?.overdue ?? 0)
  if (totalCount === 0 || dueTasks.length === 0) return null

  return (
    <div
      style={{
        backgroundColor: '#111118',
        borderRadius: '10px',
        overflow: 'hidden',
      }}
    >
      {/* Section header: accent left-border stripe + "Due today" label */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '10px 14px 6px',
        }}
      >
        {/* Accent left-border stripe: 4px × 32px */}
        <div
          style={{
            width: '4px',
            height: '32px',
            borderRadius: '2px',
            backgroundColor: accent,
            flexShrink: 0,
          }}
          aria-hidden="true"
        />
        <span
          style={{
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          Due today
        </span>
      </div>

      {/* Task rows */}
      <div style={{ padding: '0 14px 10px' }}>
        {dueTasks.map(({ task, overdueDays }) => (
          <BandTaskRow
            key={task.id}
            task={task}
            dueOverdueDays={overdueDays}
          />
        ))}
      </div>
    </div>
  )
}
