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
 *   [FAB — fixed 56px accent, above BottomTabs]
 *
 * State management:
 *   - activeListId: which list is currently shown (useState, no URL param per UI-SPEC)
 *   - detailTask: which task is open in TaskDetailSheet (null = create mode)
 *   - detailOpen: whether the sheet is open
 *   - listPickerOpen: phone list picker bottom sheet
 *
 * UndoToast is rendered here (global, fixed position) so it's always visible
 * regardless of scroll position.
 *
 * Security note (T-27-TI): task content flows through TaskRow/TaskDetailSheet;
 * dangerouslySetInnerHTML is never used on task content (enforced in those files).
 */

import { useState } from 'react'
import { Plus, ChevronDown } from 'lucide-react'
import { TaskListSidebar } from './TaskListSidebar'
import { TaskListView } from './TaskListView'
import { TaskDetailSheet } from './TaskDetailSheet'
import { UndoToast } from './UndoToast'
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

  const allLists = [{ id: 'inbox', name: 'Inbox' }, ...lists]
  const activeListName = allLists.find((l) => l.id === activeListId)?.name ?? 'Inbox'

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
        {/* Scrim */}
        <div
          onClick={() => setListPickerOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(10,10,10,0.7)',
            zIndex: 80,
          }}
          aria-hidden="true"
        />
        {/* Bottom sheet */}
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
            zIndex: 81,
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
        {/* Phone header: current list name + picker chevron */}
        <div
          className="md:hidden"
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

        {/* Desktop + phone content row */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Desktop sidebar */}
          <div className="hidden md:block">
            <TaskListSidebar
              activeListId={activeListId}
              onSelect={setActiveListId}
            />
          </div>

          {/* Task list view */}
          <TaskListView
            listId={activeListId}
            listName={activeListName}
            onOpenTask={handleOpenTask}
          />
        </div>

        {/* Phone FAB — fixed 56px accent circle above BottomTabs */}
        <button
          onClick={openCreate}
          className="md:hidden"
          style={{
            position: 'fixed',
            right: '16px',
            bottom: 'calc(env(safe-area-inset-bottom, 0px) + 76px)', // above BottomTabs 64px + 12px gap
            width: '56px',
            height: '56px',
            borderRadius: '28px',
            backgroundColor: accent,
            border: 'none',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: '0 4px 16px rgba(99,102,241,0.5)',
            zIndex: 40,
          }}
          aria-label="Add task"
        >
          <Plus size={24} strokeWidth={2} aria-hidden="true" />
        </button>
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
