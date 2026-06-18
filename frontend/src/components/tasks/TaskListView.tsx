/**
 * TaskListView.tsx — Scrollable task list with sort/group control header.
 *
 * Renders:
 *   1. SortGroupControl header
 *   2. Loading skeleton (aria-label "Loading tasks…")
 *   3. Error state
 *   4. Empty state (exact verbatim copy from UI-SPEC § Copywriting Contract)
 *   5. Task rows (grouped by due date bucket when Group=On)
 *
 * Sort behavior (D-18):
 *   - Due date: sort by due_date ascending (null last)
 *   - Priority: sort by priority (high > medium > low > none)
 *
 * Group behavior:
 *   - On: group into Today / This week / Later / No date buckets
 *   - Off: flat list, sorted by current sort mode
 *
 * T-27-TI: task titles and notes are rendered as plain text children. Never
 * use dangerouslySetInnerHTML on task content.
 */

import { useState, useMemo } from 'react'
import { useTasks } from '../../hooks/useTasks'
import { SortGroupControl, type SortMode, type SortGroupState } from './SortGroupControl'
import type { Task } from '../../api/tasks'
import {
  dominant,
  skeleton,
  textPrimary,
  textSecondary,
  border,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TaskListViewProps {
  listId: string
  listName?: string
  /** Called to open TaskDetailSheet for a task (edit) or undefined (create). */
  onOpenTask: (task?: Task) => void
}

// ---------------------------------------------------------------------------
// Sort / group helpers
// ---------------------------------------------------------------------------

const PRIORITY_RANK: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
  none: 3,
}

function sortTasks(tasks: Task[], sort: SortMode): Task[] {
  return [...tasks].sort((a, b) => {
    if (sort === 'priority') {
      const pa = PRIORITY_RANK[a.priority] ?? 3
      const pb = PRIORITY_RANK[b.priority] ?? 3
      if (pa !== pb) return pa - pb
      // Secondary: due date
      if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date)
      if (a.due_date) return -1
      if (b.due_date) return 1
      return 0
    }
    // due_date mode
    if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date)
    if (a.due_date) return -1
    if (b.due_date) return 1
    return 0
  })
}

type DateBucket = 'Today' | 'This week' | 'Later' | 'No date'

function getDateBucket(dueDateStr: string | null): DateBucket {
  if (!dueDateStr) return 'No date'
  const today = new Date()
  const todayStr = today.toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })
  if (dueDateStr <= todayStr) return 'Today' // today or overdue shown in Today bucket
  // Get end of this week (Sunday)
  const todayDate = new Date(todayStr + 'T00:00:00')
  const dayOfWeek = todayDate.getDay() // 0=Sun
  const daysToEndOfWeek = 6 - dayOfWeek
  const endOfWeek = new Date(todayDate)
  endOfWeek.setDate(todayDate.getDate() + daysToEndOfWeek)
  const endOfWeekStr = endOfWeek.toLocaleDateString('en-CA')
  if (dueDateStr <= endOfWeekStr) return 'This week'
  return 'Later'
}

function groupTasks(
  tasks: Task[],
): { bucket: DateBucket; tasks: Task[] }[] {
  const buckets: DateBucket[] = ['Today', 'This week', 'Later', 'No date']
  const grouped: Record<DateBucket, Task[]> = {
    Today: [],
    'This week': [],
    Later: [],
    'No date': [],
  }
  for (const t of tasks) {
    grouped[getDateBucket(t.due_date)].push(t)
  }
  return buckets
    .filter((b) => grouped[b].length > 0)
    .map((b) => ({ bucket: b, tasks: grouped[b] }))
}

// ---------------------------------------------------------------------------
// Skeleton row
// ---------------------------------------------------------------------------

function SkeletonRow() {
  return (
    <div
      className="animate-pulse"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '0 16px',
        height: '52px',
        borderBottom: `1px solid ${border}`,
      }}
      aria-hidden="true"
    >
      <div style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: skeleton, flexShrink: 0 }} />
      <div style={{ flex: 1, height: '14px', borderRadius: '4px', backgroundColor: skeleton }} />
      <div style={{ width: '56px', height: '20px', borderRadius: '4px', backgroundColor: skeleton }} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Group divider
// ---------------------------------------------------------------------------

function GroupDivider({ label }: { label: string }) {
  return (
    <div
      style={{
        padding: '8px 16px 4px',
        fontSize: typography.label.fontSize,
        fontWeight: 600,
        fontFamily,
        color: textSecondary,
        letterSpacing: '0.04em',
        textTransform: 'uppercase' as const,
        backgroundColor: dominant,
        borderBottom: `1px solid ${border}`,
      }}
    >
      {label}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lazy-loaded TaskRow — avoids circular imports with TaskDetailSheet
// We import it here lazily (direct import, TypeScript handles circular fine
// since TaskRow doesn't import TaskListView).
// ---------------------------------------------------------------------------

import { TaskRow } from './TaskRow'

// ---------------------------------------------------------------------------
// TaskListView
// ---------------------------------------------------------------------------

export function TaskListView({ listId, onOpenTask }: TaskListViewProps) {
  const { data: tasks, isLoading, isError } = useTasks(listId)

  const [sortGroup, setSortGroup] = useState<SortGroupState>({
    sort: 'due_date',
    group: 'off',
  })

  const processedTasks = useMemo(() => {
    if (!tasks) return []
    return sortTasks(tasks, sortGroup.sort)
  }, [tasks, sortGroup.sort])

  const grouped = useMemo(() => {
    if (sortGroup.group === 'off') return null
    return groupTasks(processedTasks)
  }, [processedTasks, sortGroup.group])

  const isInbox = listId === 'inbox'

  // ----- Loading -----
  if (isLoading) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: dominant }}>
        <SortGroupControl value={sortGroup} onChange={setSortGroup} />
        <div aria-label="Loading tasks…" role="status">
          {[1, 2, 3, 4, 5].map((i) => (
            <SkeletonRow key={i} />
          ))}
        </div>
      </div>
    )
  }

  // ----- Error -----
  if (isError) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: dominant }}>
        <SortGroupControl value={sortGroup} onChange={setSortGroup} />
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '32px 16px',
            gap: '8px',
          }}
        >
          <span style={{ fontSize: typography.body.fontSize, fontFamily, color: textSecondary }}>
            Couldn't load tasks.
          </span>
        </div>
      </div>
    )
  }

  // ----- Empty state -----
  if (!tasks || tasks.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: dominant }}>
        <SortGroupControl value={sortGroup} onChange={setSortGroup} />
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '32px 16px',
            gap: '8px',
            textAlign: 'center',
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: typography.body.fontSize,
              fontWeight: 600,
              fontFamily,
              color: textPrimary,
            }}
          >
            {isInbox ? 'Your Inbox is clear.' : 'This list is empty.'}
          </p>
          <p
            style={{
              margin: 0,
              fontSize: typography.label.fontSize,
              fontFamily,
              color: textSecondary,
            }}
          >
            {isInbox
              ? 'Press N or tap + to add a task.'
              : 'Add tasks using the + button or press N.'}
          </p>
        </div>
      </div>
    )
  }

  // ----- Task list -----
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: dominant, overflowY: 'auto' }}>
      <SortGroupControl value={sortGroup} onChange={setSortGroup} />

      {grouped ? (
        // Grouped view
        grouped.map(({ bucket, tasks: bucketTasks }) => (
          <div key={bucket}>
            <GroupDivider label={bucket} />
            {bucketTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                listId={listId}
                onOpenTask={() => onOpenTask(task)}
              />
            ))}
          </div>
        ))
      ) : (
        // Flat sorted view
        processedTasks.map((task) => (
          <TaskRow
            key={task.id}
            task={task}
            listId={listId}
            onOpenTask={() => onOpenTask(task)}
          />
        ))
      )}
    </div>
  )
}
