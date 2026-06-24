/**
 * TasksPage.tsx — Root /tasks route component.
 *
 * Desktop layout (≥ 768px):
 *   [App Sidebar 64px] | [TaskListSidebar 200px] | [TaskListView flex-1]
 *
 * Phone layout (< 768px):
 *   [Current List Header + picker] → bottom sheet picker
 *   [Sort/Group Control]
 *   [TaskListView — scrollable]
 *   [TaskFAB — fixed 56px accent, above BottomTabs; opens QuickAddBar bottom sheet]
 *
 * State management:
 *   - activeListId: which list is currently shown (useState, no URL param per UI-SPEC)
 *   - detailTask: which task is open in TaskDetailSheet (null = create mode)
 *   - detailOpen: whether the sheet is open
 *   - listPickerOpen: phone list picker bottom sheet
 *
 * Quick-add: desktop shows a persistent QuickAddBar at the top of the task
 * column (always visible). The N-key shortcut (D-10) — pressed when not focused
 * in an input/textarea — focuses that bar. Phone uses the FAB → bottom sheet.
 *
 * UndoToast is rendered here (global, fixed position) so it's always visible
 * regardless of scroll position.
 *
 * Security note (T-27-TI): task content flows through TaskRow/TaskDetailSheet
 * as plain text React children — never via raw HTML injection (enforced there).
 */

import { useState, useEffect } from 'react'
import { ChevronDown } from 'lucide-react'
import { TaskListSidebar } from './TaskListSidebar'
import { TaskListView } from './TaskListView'
import { TaskDetailSheet } from './TaskDetailSheet'
import { UndoToast } from './UndoToast'
import { TaskFAB } from './TaskFAB'
import { QuickAddBar } from './QuickAddBar'
import { useTaskLists } from '../../hooks/useTaskLists'
import type { Task } from '../../api/tasks'
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
// TasksPage
// ---------------------------------------------------------------------------

export function TasksPage() {
  const [activeListId, setActiveListId] = useState<string>('inbox')
  const [detailTask, setDetailTask] = useState<Task | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [listPickerOpen, setListPickerOpen] = useState(false)

  const { data: lists = [] } = useTaskLists()

  // GET /api/task-lists already prepends the implicit Inbox; use the API list
  // directly so the Inbox entry is not duplicated in the picker/header.
  const allLists = lists
  const activeListName = allLists.find((l) => l.id === activeListId)?.name ?? 'Inbox'

  // ---------------------------------------------------------------------------
  // Desktop N-key shortcut
  // ---------------------------------------------------------------------------

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Guard: only fire when not focused in a text input/textarea/contenteditable
      const el = document.activeElement as HTMLElement | null
      if (!el) return
      const tag = el.tagName.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || el.isContentEditable) return
      // Also guard meta/ctrl combos (browser shortcuts)
      if (e.metaKey || e.ctrlKey || e.altKey) return

      if (e.key === 'n' || e.key === 'N') {
        e.preventDefault()
        // Focus the always-present desktop quick-add input.
        const input = document.querySelector('[data-quickadd] input') as HTMLInputElement | null
        input?.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  // ---------------------------------------------------------------------------
  // Task detail handlers
  // ---------------------------------------------------------------------------

  function openCreate() {
    setDetailTask(null)
    setDetailOpen(true)
  }

  function openEdit(task: Task) {
    setDetailTask(task)
    setDetailOpen(true)
  }

  function handleOpenTask(task?: Task) {
    if (task) {
      openEdit(task)
    } else {
      openCreate()
    }
  }

  function handleDetailClose() {
    setDetailOpen(false)
  }

  function handleSelectList(listId: string) {
    setActiveListId(listId)
    setListPickerOpen(false)
  }

  // ---------------------------------------------------------------------------
  // Phone list picker bottom sheet
  // ---------------------------------------------------------------------------

  function PhoneListPicker() {
    if (!listPickerOpen) return null
    return (
      <>
        {/* Scrim — z:190 covers BottomTabs (z:100) so the picker isn't buried. */}
        <div
          onClick={() => setListPickerOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(10,10,10,0.7)',
            zIndex: 190,
          }}
          aria-hidden="true"
        />
        {/* Bottom sheet — z:191 above the tab bar so the full list is visible. */}
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Select list"
          style={{
            position: 'fixed',
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: secondary,
            borderTop: `1px solid ${border}`,
            borderRadius: '16px 16px 0 0',
            zIndex: 191,
            maxHeight: '60dvh',
            overflowY: 'auto',
            paddingBottom: 'env(safe-area-inset-bottom, 16px)',
          }}
        >
          <div
            style={{
              padding: '16px',
              fontSize: typography.heading.fontSize,
              fontWeight: typography.heading.fontWeight,
              fontFamily,
              color: textPrimary,
              borderBottom: `1px solid ${border}`,
            }}
          >
            Lists
          </div>
          {allLists.map((list) => {
            const isActive = list.id === activeListId
            return (
              <button
                key={list.id}
                onClick={() => handleSelectList(list.id)}
                style={{
                  display: 'block',
                  width: '100%',
                  minHeight: '52px',
                  padding: '0 16px',
                  border: 'none',
                  borderLeft: isActive ? `4px solid ${accent}` : '4px solid transparent',
                  backgroundColor: isActive ? `${accent}18` : 'transparent',
                  color: isActive ? textPrimary : textSecondary,
                  fontSize: typography.body.fontSize,
                  fontFamily,
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
                aria-current={isActive ? 'true' : undefined}
              >
                {list.name}
              </button>
            )
          })}
        </div>
      </>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* Main layout */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          overflow: 'hidden',
          backgroundColor: dominant,
        }}
      >
        {/* Phone header: current list name + picker chevron (phone only).
            md:hidden lives on this wrapper — NOT on the inline-styled flex row,
            because an inline `display` would override the Tailwind utility. */}
        <div className="md:hidden">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            height: '52px',
            padding: '0 16px',
            borderBottom: `1px solid ${border}`,
            backgroundColor: secondary,
            flexShrink: 0,
          }}
        >
          <button
            onClick={() => setListPickerOpen(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              border: 'none',
              backgroundColor: 'transparent',
              color: textPrimary,
              fontSize: typography.heading.fontSize,
              fontWeight: typography.heading.fontWeight,
              fontFamily,
              cursor: 'pointer',
              padding: 0,
            }}
            aria-haspopup="dialog"
            aria-expanded={listPickerOpen}
            aria-label={`Current list: ${activeListName}. Tap to change.`}
          >
            {activeListName}
            <ChevronDown size={16} color={textSecondary} aria-hidden="true" />
          </button>
        </div>
        </div>

        {/* Desktop + phone content row */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Desktop sidebar */}
          <div className="hidden md:block">
            <TaskListSidebar
              activeListId={activeListId}
              onSelect={setActiveListId}
            />
          </div>

          {/* Main task column: desktop inline quick-add bar + task list */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {/* Desktop persistent quick-add bar — always visible at the top of
                the task column (the N key focuses it). Hidden on phone, which
                uses the FAB → bottom-sheet QuickAddBar instead. */}
            <div className="hidden md:block" data-quickadd style={{ flexShrink: 0 }}>
              <QuickAddBar
                defaultListId={activeListId}
                persistent
                autoFocus={false}
              />
            </div>

            <TaskListView
              listId={activeListId}
              listName={activeListName}
              onOpenTask={handleOpenTask}
            />
          </div>
        </div>

        {/* Phone TaskFAB — renders the 56px accent FAB + bottom sheet QuickAddBar */}
        <TaskFAB defaultListId={activeListId} />
      </div>

      {/* Phone list picker */}
      <PhoneListPicker />

      {/* Task detail sheet */}
      <TaskDetailSheet
        task={detailTask}
        defaultListId={activeListId}
        open={detailOpen}
        onClose={handleDetailClose}
      />

      {/* Undo toast — global fixed overlay */}
      <UndoToast />
    </>
  )
}
