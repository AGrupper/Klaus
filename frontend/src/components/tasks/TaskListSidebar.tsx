/**
 * TaskListSidebar.tsx — Desktop 200px left sidebar for list navigation.
 *
 * Layout:
 *   - "Tasks" heading
 *   - Inbox (prepended server-side by GET /api/task-lists, rendered first)
 *   - User-created lists (from useTaskLists)
 *   - "New list" inline input at bottom
 *
 * Active state: 4px left border in accent (#6366F1) + slightly lighter background (#222222).
 * Touch targets: ≥44px height per item.
 *
 * Desktop only — hidden on phone (TasksPage handles the phone header picker).
 */

import { useState, useRef, useEffect } from 'react'
import { Plus } from 'lucide-react'
import { useTaskLists, useCreateList } from '../../hooks/useTaskLists'
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
// Props
// ---------------------------------------------------------------------------

interface TaskListSidebarProps {
  /** The currently active list id ('inbox' or a user list id). */
  activeListId: string
  /** Called when the user selects a different list. */
  onSelect: (listId: string) => void
}

// ---------------------------------------------------------------------------
// TaskListSidebar
// ---------------------------------------------------------------------------

export function TaskListSidebar({ activeListId, onSelect }: TaskListSidebarProps) {
  const { data: lists = [], isLoading } = useTaskLists()
  const createList = useCreateList()

  const [showNewListInput, setShowNewListInput] = useState(false)
  const [newListName, setNewListName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus the input when it appears
  useEffect(() => {
    if (showNewListInput && inputRef.current) {
      inputRef.current.focus()
    }
  }, [showNewListInput])

  function handleCreateList() {
    const trimmed = newListName.trim()
    if (!trimmed) {
      setShowNewListInput(false)
      return
    }
    createList.mutate(trimmed, {
      onSuccess: () => {
        setNewListName('')
        setShowNewListInput(false)
      },
    })
    setNewListName('')
    setShowNewListInput(false)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      handleCreateList()
    } else if (e.key === 'Escape') {
      setNewListName('')
      setShowNewListInput(false)
    }
  }

  // GET /api/task-lists already prepends the implicit Inbox; render the API
  // list directly. (Prepending Inbox here too would duplicate the entry.)
  const allLists = lists

  return (
    <nav
      aria-label="Task lists"
      style={{
        width: '200px',
        flexShrink: 0,
        backgroundColor: secondary,
        borderRight: `1px solid ${border}`,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Heading */}
      <div
        style={{
          padding: '16px 16px 8px',
          fontSize: typography.heading.fontSize,
          fontWeight: typography.heading.fontWeight,
          lineHeight: typography.heading.lineHeight,
          fontFamily,
          color: textPrimary,
          flexShrink: 0,
        }}
      >
        Tasks
      </div>

      {/* List items */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {isLoading ? (
          <div
            style={{
              padding: '8px 16px',
              color: textSecondary,
              fontSize: typography.label.fontSize,
              fontFamily,
            }}
          >
            Loading…
          </div>
        ) : (
          allLists.map((list) => {
            const isActive = list.id === activeListId
            return (
              <button
                key={list.id}
                onClick={() => onSelect(list.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  width: '100%',
                  minHeight: '44px',
                  padding: '0 16px',
                  border: 'none',
                  borderLeft: isActive ? `4px solid ${accent}` : '4px solid transparent',
                  backgroundColor: isActive ? '#222222' : 'transparent',
                  color: isActive ? textPrimary : textSecondary,
                  fontSize: typography.body.fontSize,
                  fontWeight: isActive ? 600 : 400,
                  fontFamily,
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background-color 0.15s, color 0.15s',
                }}
                aria-current={isActive ? 'page' : undefined}
              >
                {list.name}
              </button>
            )
          })
        )}
      </div>

      {/* New list section */}
      <div
        style={{
          flexShrink: 0,
          borderTop: `1px solid ${border}`,
          padding: '8px',
        }}
      >
        {showNewListInput ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <input
              ref={inputRef}
              type="text"
              value={newListName}
              onChange={(e) => setNewListName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="List name"
              maxLength={64}
              style={{
                width: '100%',
                padding: '8px 10px',
                backgroundColor: dominant,
                border: `1px solid ${border}`,
                borderRadius: '6px',
                color: textPrimary,
                fontSize: typography.label.fontSize,
                fontFamily,
                outline: 'none',
                boxSizing: 'border-box',
              }}
              aria-label="New list name"
            />
            <button
              onClick={handleCreateList}
              style={{
                width: '100%',
                height: '36px',
                backgroundColor: accent,
                border: 'none',
                borderRadius: '6px',
                color: '#FFFFFF',
                fontSize: typography.label.fontSize,
                fontWeight: 600,
                fontFamily,
                cursor: 'pointer',
              }}
            >
              Create list
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowNewListInput(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              width: '100%',
              minHeight: '44px',
              padding: '0 8px',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              fontSize: typography.label.fontSize,
              fontFamily,
              cursor: 'pointer',
            }}
            aria-label="Add new list"
          >
            <Plus size={14} strokeWidth={2} aria-hidden="true" />
            New list
          </button>
        )}
      </div>
    </nav>
  )
}
