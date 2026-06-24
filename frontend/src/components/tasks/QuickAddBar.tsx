/**
 * QuickAddBar.tsx — Live-parsing quick-add input for Klaus Hub tasks.
 *
 * Behaviour (D-10, UI-SPEC § Quick-add):
 *   - Single-line input with placeholder "Add a task…  #list  !priority  date"
 *   - Calls parseTaskInput(value, refDate) on every keystroke → resolves token chips
 *     inline: date chip ("D Mon" e.g. "19 Jun"), priority chip ("High"/"Medium"/"Low"),
 *     list chip (fuzzy-matched to existing list name or "Inbox")
 *   - "Add task" button or Enter submits: fuzzy-match list_name → list_id (unmatched → "inbox"),
 *     calls useCreateTask with {title, due_date, priority, list_id}, clears input
 *   - Escape or blur dismisses (calls onClose without saving)
 *
 * Usage contexts (UI-SPEC § Tasks Page Interaction Contracts):
 *   - Phone: mounted inside a bottom sheet overlay (slide-up)
 *   - Desktop: mounted inline above TaskListView when N key is pressed
 *
 * Security (T-27-TI): task title passed through parseTaskInput (safe charset strip);
 * chip labels are static strings or the parsed priority/list name — plain React children,
 * never via raw HTML injection.
 */

import { useState, useRef, useEffect } from 'react'
import { parseTaskInput } from '../../utils/parseTaskInput'
import { useCreateTask } from '../../hooks/useTasks'
import { useTaskLists } from '../../hooks/useTaskLists'
import {
  accent,
  border,
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

interface QuickAddBarProps {
  /** The list_id to create tasks into when no #list token is present or matched. */
  defaultListId?: string
  /** Called when the user dismisses (Escape / blur) without submitting. */
  onClose?: () => void
  /** Called after a task is successfully submitted (input cleared internally). */
  onSubmit?: () => void
  /** Whether to auto-focus the input on mount. Defaults to true. */
  autoFocus?: boolean
  /**
   * Persistent mode (desktop top bar): the bar is always mounted, so blur and
   * Escape do NOT dismiss it (Escape just blurs the input). Defaults to false
   * (phone bottom-sheet mode, where blur/Escape close the sheet).
   */
  persistent?: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a YYYY-MM-DD date string as "D Mon" (e.g. "19 Jun"). */
function formatDateChip(isoDate: string): string {
  try {
    // Parse as noon UTC to avoid timezone boundary issues when displaying
    const [y, m, d] = isoDate.split('-').map(Number)
    const date = new Date(Date.UTC(y, m - 1, d, 12))
    const day = date.getUTCDate()
    const month = date.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
    return `${day} ${month}`
  } catch {
    return isoDate
  }
}

/** Priority chip label strings per UI-SPEC Copywriting. */
const PRIORITY_LABEL: Record<string, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

// ---------------------------------------------------------------------------
// QuickAddBar
// ---------------------------------------------------------------------------

export function QuickAddBar({
  defaultListId = 'inbox',
  onClose,
  onSubmit,
  autoFocus = true,
  persistent = false,
}: QuickAddBarProps) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: userLists = [] } = useTaskLists()
  // GET /api/task-lists already prepends the implicit Inbox; use it directly.
  const allLists = userLists
  const defaultListName = allLists.find((l) => l.id === defaultListId)?.name ?? 'Inbox'

  // Parse the current input value for live chip display
  const parsed = parseTaskInput(value, new Date())

  // Fuzzy-match parsed.list_name → list_id
  function resolveListId(listName: string | null): { id: string; name: string } {
    if (!listName) {
      const def = allLists.find((l) => l.id === defaultListId) ?? { id: 'inbox', name: 'Inbox' }
      return def
    }
    const needle = listName.toLowerCase()
    // Exact match first
    const exact = allLists.find((l) => l.name.toLowerCase() === needle)
    if (exact) return exact
    // Prefix / contains match
    const partial = allLists.find(
      (l) => l.name.toLowerCase().startsWith(needle) || l.name.toLowerCase().includes(needle),
    )
    if (partial) return partial
    // Unmatched → inbox
    return { id: 'inbox', name: 'Inbox' }
  }

  const resolvedList = resolveListId(parsed.list_name)

  const createTask = useCreateTask(resolvedList.id)

  // Auto-focus on mount
  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus()
    }
  }, [autoFocus])

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    } else if (e.key === 'Escape') {
      if (persistent) {
        inputRef.current?.blur()
      } else {
        onClose?.()
      }
    }
  }

  function handleSubmit() {
    const title = parsed.title.trim()
    if (!title) {
      onClose?.()
      return
    }

    createTask.mutate({
      title,
      due_date: parsed.due_date ?? undefined,
      priority: (parsed.priority ?? 'none') as 'none' | 'low' | 'medium' | 'high',
      list_id: resolvedList.id,
    })

    // Clear input for another entry
    setValue('')
    onSubmit?.()
    // Re-focus for rapid multi-entry
    inputRef.current?.focus()
  }

  const hasChips = parsed.due_date !== null || parsed.priority !== null || parsed.list_name !== null

  return (
    <div
      style={{
        backgroundColor: secondary,
        // Persistent desktop bar sits at the TOP of the column → border below it.
        // Phone bottom-sheet sits at the BOTTOM → border above it.
        ...(persistent
          ? { borderBottom: `1px solid ${border}` }
          : { borderTop: `1px solid ${border}` }),
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}
    >
      {/* Input row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={(e) => {
            // Persistent (desktop) bar never auto-dismisses on blur.
            if (persistent) return
            // Dismiss if focus moves completely outside the quick-add area
            // (not to the submit button or chips within)
            const relatedTarget = e.relatedTarget as HTMLElement | null
            if (!relatedTarget || !e.currentTarget.closest('[data-quickadd]')?.contains(relatedTarget)) {
              onClose?.()
            }
          }}
          placeholder={`Add a task to "${defaultListName}"…`}
          aria-label="Quick add task"
          style={{
            flex: 1,
            minHeight: '44px',
            padding: '0 12px',
            backgroundColor: dominant,
            border: `1px solid ${border}`,
            borderRadius: '8px',
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontFamily,
            outline: 'none',
          }}
        />

        {/* "Add task" submit button */}
        <button
          onClick={handleSubmit}
          // Keep focus on the input when the button is pressed. Without this,
          // tapping the button blurs the input first; on iOS the blur fires with
          // a null relatedTarget, so the onBlur handler above closes the sheet
          // before this click runs and the submit is lost. preventDefault on
          // mousedown stops the focus shift while still allowing the click.
          onMouseDown={(e) => e.preventDefault()}
          disabled={!parsed.title.trim()}
          style={{
            height: '44px',
            padding: '0 14px',
            backgroundColor: parsed.title.trim() ? accent : `${accent}60`,
            border: 'none',
            borderRadius: '8px',
            color: '#FFFFFF',
            fontSize: typography.label.fontSize,
            fontWeight: 600,
            fontFamily,
            cursor: parsed.title.trim() ? 'pointer' : 'not-allowed',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          Add task
        </button>
      </div>

      {/* Live-resolved token chips — only shown when at least one token is parsed */}
      {hasChips && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            flexWrap: 'wrap',
          }}
        >
          {/* Date chip */}
          {parsed.due_date !== null && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                height: '24px',
                padding: '0 8px',
                backgroundColor: '#1F1F2F',
                border: `1px solid ${accent}60`,
                borderRadius: '12px',
                color: accent,
                fontSize: typography.label.fontSize,
                fontFamily,
              }}
            >
              {formatDateChip(parsed.due_date)}
            </span>
          )}

          {/* Priority chip */}
          {parsed.priority !== null && parsed.priority !== 'none' && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                height: '24px',
                padding: '0 8px',
                backgroundColor:
                  parsed.priority === 'high'
                    ? '#2A1A1A'
                    : parsed.priority === 'medium'
                      ? '#2A2010'
                      : 'transparent',
                border: `1px solid ${parsed.priority === 'high' ? '#F87171' : parsed.priority === 'medium' ? '#FBBF24' : '#9CA3AF'}40`,
                borderRadius: '12px',
                color:
                  parsed.priority === 'high'
                    ? '#F87171'
                    : parsed.priority === 'medium'
                      ? '#FBBF24'
                      : textSecondary,
                fontSize: typography.label.fontSize,
                fontFamily,
              }}
            >
              {PRIORITY_LABEL[parsed.priority] ?? parsed.priority}
            </span>
          )}

          {/* List chip — shown when a #list token is present and resolved */}
          {parsed.list_name !== null && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                height: '24px',
                padding: '0 8px',
                backgroundColor: '#1A1A2A',
                border: `1px solid ${border}`,
                borderRadius: '12px',
                color: textSecondary,
                fontSize: typography.label.fontSize,
                fontFamily,
              }}
            >
              {resolvedList.name}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
