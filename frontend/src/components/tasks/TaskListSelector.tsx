/**
 * TaskListSelector.tsx — Shared list-picker dropdown/sheet.
 *
 * Desktop: renders as an inline dropdown anchored to the trigger.
 * Phone: same presentation (simplified — no full bottom sheet for list selector
 *        since it's only used inside TaskDetailSheet which already handles the
 *        bottom sheet pattern; the phone list-navigation picker in TasksPage is
 *        implemented directly there for layout reasons).
 *
 * Used by:
 *   - TaskDetailSheet (list field picker)
 *   - TasksPage phone header (current list picker)
 */

import { type TaskList } from '../../api/task-lists'
import {
  secondary,
  border,
  textPrimary,
  textSecondary,
  accent,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TaskListSelectorProps {
  /** Currently selected list id ('inbox' or a user list id). */
  value: string
  /** Called when a list is selected. */
  onChange: (listId: string) => void
  /** The user-created lists (Inbox is prepended automatically). */
  lists: TaskList[]
  /** Whether the dropdown is open. */
  open: boolean
  /** Called to close the dropdown. */
  onClose: () => void
}

// ---------------------------------------------------------------------------
// TaskListSelector
// ---------------------------------------------------------------------------

export function TaskListSelector({
  value,
  onChange,
  lists,
  open,
  onClose,
}: TaskListSelectorProps) {
  if (!open) return null

  const allLists = [
    { id: 'inbox', name: 'Inbox' },
    ...lists,
  ]

  function handleSelect(listId: string) {
    onChange(listId)
    onClose()
  }

  return (
    <>
      {/* Invisible backdrop to capture outside clicks */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 49,
        }}
        aria-hidden="true"
      />

      {/* Dropdown panel */}
      <div
        role="listbox"
        aria-label="Select list"
        style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          marginTop: '4px',
          minWidth: '180px',
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          borderRadius: '10px',
          overflow: 'hidden',
          zIndex: 50,
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
        }}
      >
        {allLists.map((list) => {
          const isActive = list.id === value
          return (
            <button
              key={list.id}
              role="option"
              aria-selected={isActive}
              onClick={() => handleSelect(list.id)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '10px 14px',
                border: 'none',
                backgroundColor: isActive ? `${accent}22` : 'transparent',
                color: isActive ? accent : textPrimary,
                fontSize: typography.label.fontSize,
                fontWeight: isActive ? 600 : 400,
                fontFamily,
                cursor: 'pointer',
                borderLeft: isActive ? `3px solid ${accent}` : '3px solid transparent',
                transition: 'background-color 0.1s',
              }}
            >
              {list.name}
            </button>
          )
        })}

        {allLists.length === 1 && (
          <div
            style={{
              padding: '10px 14px',
              color: textSecondary,
              fontSize: typography.label.fontSize,
              fontFamily,
            }}
          >
            No lists yet
          </div>
        )}
      </div>
    </>
  )
}
